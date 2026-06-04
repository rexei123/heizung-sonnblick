"""Pydantic-Schemas fuer Devices-API."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from heizung.models.enums import DeviceKind, DeviceVendor, OverrideSource

_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")


def _normalize_eui(value: str | None) -> str | None:
    """LoRaWAN-EUIs konsistent in lowercase-hex speichern."""
    if value is None:
        return None
    if not _HEX16.fullmatch(value):
        raise ValueError("EUI muss 16 Hex-Zeichen sein")
    return value.lower()


class DeviceCreate(BaseModel):
    """Eingabe fuer POST /api/v1/devices.

    Sprint 13b.1 (AE-57): kein ``is_active``-Feld mehr — Devices werden
    immer aktiv angelegt (``retired_at=NULL``). Lifecycle-Aenderungen
    laufen ueber ``services.device_service.retire_device`` /
    ``replace_device``, nicht ueber Create/Update.
    """

    dev_eui: str = Field(
        ..., description="LoRaWAN DevEUI (8 Byte hex, 16 Zeichen, case-insensitive)"
    )
    app_eui: str | None = Field(
        default=None, description="LoRaWAN AppEUI/JoinEUI (optional, 16 Hex-Zeichen)"
    )
    kind: DeviceKind = Field(..., description="thermostat | sensor")
    vendor: DeviceVendor = Field(..., description="mclimate | milesight | manual")
    model: str = Field(..., min_length=1, max_length=50)
    label: str | None = Field(default=None, max_length=200)
    heating_zone_id: int | None = Field(
        default=None,
        description="FK auf heating_zone.id; NULL solange ungeordnet (Pool oder Provisioning).",
    )

    @field_validator("dev_eui")
    @classmethod
    def _v_dev_eui(cls, v: str) -> str:
        normalized = _normalize_eui(v)
        # _normalize_eui validiert + lowercased; bei valid-Input nie None.
        # `or v` ist Defensiv-Fallback, falls _normalize_eui sich aendert.
        return normalized if normalized is not None else v

    @field_validator("app_eui")
    @classmethod
    def _v_app_eui(cls, v: str | None) -> str | None:
        return _normalize_eui(v)


class DeviceUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/devices/{id}. Alle Felder optional.

    Sprint 13b.1 (AE-57): kein ``is_active``-Feld mehr. Lifecycle laeuft
    ueber dedizierte Service-Funktionen / Endpoints, nicht via Update.
    """

    app_eui: str | None = None
    kind: DeviceKind | None = None
    vendor: DeviceVendor | None = None
    model: str | None = Field(default=None, min_length=1, max_length=50)
    label: str | None = Field(default=None, max_length=200)
    # Sprint 14a (D1/D5): Hardware-/Seriennummer per Inline-Edit aenderbar.
    # Keine Format-Validierung (D3); Eindeutigkeit erzwingt der DB-Index.
    hardware_number: str | None = Field(default=None, max_length=64)
    heating_zone_id: int | None = None

    @field_validator("app_eui")
    @classmethod
    def _v_app_eui(cls, v: str | None) -> str | None:
        return _normalize_eui(v)


# ---------------------------------------------------------------------------
# Nested Read-Schemas fuer die Cross-Sicht-UI (Sprint 14a, D2)
# ---------------------------------------------------------------------------


class DeviceRoomTypeRead(BaseModel):
    """Raumtyp-Ausschnitt im Device-Nested-Response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class DeviceRoomRead(BaseModel):
    """Zimmer-Ausschnitt im Device-Nested-Response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    room_type: DeviceRoomTypeRead


class DeviceZoneRead(BaseModel):
    """Heizzone-Ausschnitt inkl. Zone-Health (AE-51/AE-53) + Zimmer-Kette.

    ``health_state`` ist die ZoneHealthBadge-Quelle (D6) — kein eigener
    API-Call noetig. Werte-Whitelist gemaess ``heating_zone.health_state``
    (AE-53 Punkt 2: ``no_device`` statt ``suspicious``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    health_state: Literal["healthy", "degraded", "silent", "no_device"]
    room: DeviceRoomRead


class DeviceActiveOverrideRead(BaseModel):
    """Aktiver Override fuer die Zone des Geraets (read-only, AE-61).

    Quelle ist ``override_service.get_active`` (Zone>Room-Aufloesung,
    ``revoked_at IS NULL AND expires_at > now``). Reine Diagnose-Anzeige —
    die Steuerung lebt auf den Zimmer-Seiten (AE-61).
    """

    source: OverrideSource
    setpoint_celsius: Decimal
    started_at: datetime
    expires_at: datetime

    @field_serializer("setpoint_celsius")
    def _decimal_to_float(self, v: Decimal) -> float:
        return float(v)


class DeviceLatestReadingRead(BaseModel):
    """Juengster SensorReading-Frame fuer die Diagnose-Kacheln (D5).

    ``valve_position`` 0..100 % (Frontend rendert > 100 / < 0 defensiv als
    "nicht verfuegbar", D7). ``open_window`` / ``attached_backplate`` sind
    NULL wenn das Codec-Feld im Frame fehlte (alter Codec / Recovery).

    Sprint 14b: ``temperature`` + ``battery_percent`` additiv ergaenzt
    (Thermostat-Bubbles Ist-Temp + Batterie). ``temperature`` als
    field_serializer->float (Konvention wie SensorReadingRead /
    DeviceActiveOverrideRead).
    """

    valve_position: int | None
    open_window: bool | None
    attached_backplate: bool | None
    temperature: Decimal | None = None
    battery_percent: int | None = None
    recorded_at: datetime

    @field_serializer("temperature")
    def _temp_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None


class DeviceRead(BaseModel):
    """Ausgabe fuer GET /api/v1/devices und /devices/{id}.

    Sprint 13b.1 (AE-57): ``retired_at`` / ``retired_reason`` /
    ``replaced_by_device_id`` ergaenzt. ``is_active`` entfernt — Caller
    filtern via ``retired_at IS NULL`` (Single Source of Truth).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    dev_eui: str
    app_eui: str | None
    kind: DeviceKind
    vendor: DeviceVendor
    model: str
    label: str | None
    heating_zone_id: int | None
    retired_at: datetime | None
    retired_reason: str | None
    replaced_by_device_id: int | None
    last_seen_at: datetime | None
    firmware_version: str | None = None
    health_state: Literal["healthy", "degraded", "silent", "suspicious"]
    created_at: datetime
    updated_at: datetime

    # Sprint 15d (AE-65): Batterie als orthogonale dritte Health-Achse neben
    # ``health_state`` (offline/implausible). Abgeleitet aus
    # ``latest_reading.battery_percent`` + ``alert_battery_warn_percent``, vom
    # Endpoint via model_copy gesetzt (kein ORM-Attribut, kein persistentes
    # Feld). Default "unbekannt", damit ``model_validate(device)`` greift, wenn
    # kein Reading vorliegt. PR2 kombiniert beide Achsen fuer die Sortierung.
    battery_state: Literal["ok", "warn", "kritisch", "unbekannt"] = "unbekannt"

    # Sprint 14a (D1/D2): additive Cross-Sicht-Felder. Defaults None, damit
    # ``model_validate(device)`` (from_attributes) bei fehlenden ORM-
    # Attributen (active_override, latest_reading) den Default nimmt; der
    # Endpoint befuellt sie anschliessend via model_copy.
    hardware_number: str | None = None
    heating_zone: DeviceZoneRead | None = None
    active_override: DeviceActiveOverrideRead | None = None
    latest_reading: DeviceLatestReadingRead | None = None


class DeviceAssignZoneRequest(BaseModel):
    """Request body fuer PUT /api/v1/devices/{device_id}/heating-zone."""

    heating_zone_id: int = Field(..., gt=0, description="Ziel-Heizzone")

    model_config = ConfigDict(extra="forbid")


class DeviceReplaceFromPoolRequest(BaseModel):
    """Request body fuer POST /api/v1/devices/{device_id}/replace/from-pool.

    Sprint 13b.1 (AE-57 Entscheidung 6): atomarer Pool-Reassign-Tausch.
    """

    new_pool_device_id: int = Field(
        ..., gt=0, description="Ziel-Pool-Device, das die alte Zone uebernimmt."
    )

    model_config = ConfigDict(extra="forbid")


class DeviceRetireRequest(BaseModel):
    """Request body fuer POST /api/v1/devices/{device_id}/retire.

    Sprint 13b.1 (AE-57 Entscheidung 6): Stilllegung ohne Ersatz.
    """

    reason: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Freitext-Begruendung (z.B. 'battery_dead', 'hardware_swap').",
    )

    model_config = ConfigDict(extra="forbid")


class DeviceAssignZoneResponse(BaseModel):
    """Response fuer PUT und DELETE - heating_zone_id ist None nach Detach.

    ``device_id`` ist als alias auf ``Device.id`` gemappt; der Parameter-Pfad
    der API spricht von ``device_id``, das ORM-Feld heisst nur ``id``.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    device_id: int = Field(..., validation_alias="id")
    dev_eui: str
    heating_zone_id: int | None
    label: str | None
    updated_at: datetime


class HardwareStatusResponse(BaseModel):
    """Hardware-Status-Snapshot fuer ein Geraet (Sprint 9.13c, B-LT-2-followup-1).

    Bewertet die letzten ``window_minutes`` Minuten ``sensor_reading``-Frames
    auf das Vicki-Codec-Feld ``attached_backplate``. Datenquelle ist dieselbe
    wie fuer Engine-Layer-4-Detached, aber als reine Lese-Aggregation
    (kein Engine-Pfad, kein Cache).
    """

    status: Literal["active", "inactive"] = Field(
        ...,
        description="active wenn mindestens ein True-Frame im Fenster, sonst inactive",
    )
    last_seen: datetime | None = Field(
        default=None,
        description="Juengster Frame mit attached_backplate=true im Fenster (None falls keiner)",
    )
    frames_in_window: int = Field(
        ...,
        ge=0,
        description="Anzahl Frames mit attached_backplate IS NOT NULL im Fenster",
    )
    window_minutes: int = Field(
        ...,
        gt=0,
        description="Fenster-Groesse in Minuten (heute 30, Quelle: WINDOW_STALE_THRESHOLD_MIN)",
    )
