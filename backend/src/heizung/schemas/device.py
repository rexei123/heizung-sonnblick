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

    Sprint 14b: ``temperature`` additiv ergaenzt (Thermostat-Bubbles
    Ist-Temp). ``temperature`` als field_serializer->float (Konvention wie
    SensorReadingRead / DeviceActiveOverrideRead).

    Sprint 20 (AE-72): ``battery_percent`` ist hier **ersetzt** durch
    ``battery_voltage`` — die Groesse, die der Codec liefert. Prozent war an
    dieser Stelle Scheinpraezision (0.1-V-Raster, Saettigung oberhalb
    ~3.4 V). Die **Stufe** kommt nicht von hier, sondern aus dem 24-h-Median
    (``DeviceRead.battery_state``); dieser Wert ist der letzte Frame und
    gehoert in die Messwert-Historie, nicht an den Badge.
    """

    valve_position: int | None
    open_window: bool | None
    attached_backplate: bool | None
    temperature: Decimal | None = None
    battery_voltage: Decimal | None = None
    recorded_at: datetime

    @field_serializer("temperature", "battery_voltage")
    def _decimal_to_float(self, v: Decimal | None) -> float | None:
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
    # Sprint 20e (T7/T10): Ventil-Hinweis, read-time abgeleitet aus dem
    # 2-h-Fenster (``services/valve_health.valve_verdicts``). Keine Spalte,
    # kein Beat-Task — Begruendung wie bei ``battery_state`` (AE-72 §3).
    #
    # ``ok`` heisst "im Fenster nichts auffaellig", ``unbekannt`` heisst "zu
    # wenige Messwerte im Fenster". Die beiden sind nicht dasselbe, und die
    # Oberflaeche darf sie nicht zusammenfassen: ein Geraet, das schweigt,
    # ist kein Geraet, dessen Ventil in Ordnung ist.
    # Inline-``Literal`` und kein Import aus ``services``: dieselbe
    # Konvention wie bei ``battery_state`` — die Schema-Schicht soll nicht
    # von der Service-Schicht abhaengen. Die Spiegelung gegen
    # ``valve_health.ValveState`` haelt ein Test fest.
    valve_state: Literal["ok", "ventil_klemmt_zu", "zimmer_zu_warm", "unbekannt"] = "unbekannt"
    # Der gemessene Abstand zum Urteil, in Kelvin. Bei ``ok`` und
    # ``unbekannt`` ``None``. Der **knappste** Wert des Fensters, nicht der
    # Spitzenwert — siehe ``ValveVerdict``.
    valve_delta_k: Decimal | None = None

    retired_at: datetime | None
    retired_reason: str | None
    replaced_by_device_id: int | None
    last_seen_at: datetime | None
    firmware_version: str | None = None
    health_state: Literal["healthy", "degraded", "silent", "suspicious"]
    created_at: datetime
    updated_at: datetime

    # Sprint 15d (AE-65): Batterie als orthogonale dritte Health-Achse neben
    # ``health_state`` (offline/implausible). Vom Endpoint via model_copy
    # gesetzt (kein ORM-Attribut, kein persistentes Feld). Default
    # "unbekannt", damit ``model_validate(device)`` greift, wenn kein Reading
    # vorliegt. Die Sortierung der Geraeteliste kombiniert beide Achsen.
    #
    # Sprint 20 (AE-72): Quelle ist der **Median der Geraete-Spannung ueber
    # 24 h**, nicht mehr ein Prozentwert aus dem letzten Frame. Schwellen
    # OK >= 3.0 V / schwach 2.9 V / kritisch <= 2.8 V.
    battery_state: Literal["ok", "warn", "kritisch", "unbekannt"] = "unbekannt"

    # Sprint 20 (AE-72): die Zahl, die zur Stufe gehoert. Wer sie in der
    # Oberflaeche neben die Stufe stellt ("OK · 3,1 V"), nimmt diese und
    # nicht ``latest_reading.battery_voltage`` — sonst widerspricht der Badge
    # sich selbst, sobald ein einzelner Frame unter Motorlast einbricht.
    # ``None`` wenn die Mindest-Stichprobe im Fenster nicht erreicht ist.
    battery_voltage_median: Decimal | None = None

    # Gesetzt, wenn im Fenster ein Batteriewechsel erkannt wurde (Sprung
    # >= 0.3 V nach oben). Dann zaehlen nur die Messwerte ab diesem
    # Zeitpunkt, und solange es davon weniger als drei gibt, ist
    # ``battery_state`` "unbekannt". Mit diesem Feld kann die Oberflaeche
    # den Grund nennen ("Batteriewechsel erkannt") statt einen Fehler zu
    # suggerieren — das ist rund eine halbe Stunde nach dem Wechsel.
    battery_jump_at: datetime | None = None

    # Der juengste bekannte Spannungswert und sein Zeitpunkt — unabhaengig
    # vom Bewertungs-Fenster und davon, ob eine Stufe zustande kam.
    #
    # Regel aus dem Befund vom 30.09.2026: **nie ein Badge ohne Spannung,
    # wenn irgendeine Spannung bekannt ist.** "Batterie unbekannt" ohne Zahl
    # sagt dem Hotelier nichts; "3,5 V · vor 2 h" sagt ihm, dass die Zelle
    # voll ist und das Geraet seit zwei Stunden schweigt — zwei Auskuenfte
    # statt keiner. ``battery_state`` bleibt dabei "unbekannt", weil eine
    # Stufe wirklich nicht berechenbar ist; die Oberflaeche unterscheidet
    # anhand dieser Felder, was sie zeigt.
    #
    # Beide ``None`` heisst: es wurde nie eine Spannung gemeldet (oder die
    # letzte liegt laenger zurueck als das Rueckblick-Fenster von 30 Tagen).
    battery_last_voltage: Decimal | None = None
    battery_last_at: datetime | None = None

    # Sprint 14a (D1/D2): additive Cross-Sicht-Felder. Defaults None, damit
    # ``model_validate(device)`` (from_attributes) bei fehlenden ORM-
    # Attributen (active_override, latest_reading) den Default nimmt; der
    # Endpoint befuellt sie anschliessend via model_copy.
    hardware_number: str | None = None
    heating_zone: DeviceZoneRead | None = None
    active_override: DeviceActiveOverrideRead | None = None
    latest_reading: DeviceLatestReadingRead | None = None

    @field_serializer("battery_voltage_median", "battery_last_voltage")
    def _volt_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None


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

    **Sprint 20e (T5): zwei Quellen, und die Antwort sagt welche.**

    Fuer ein **zugeordnetes** Geraet mit ``device.mounted_confirmed_at``
    urteilt der Nachweis: einmal belegt montiert, bleibt montiert, solange
    das Geraet an derselben Zone haengt (``source="mounted_confirmed"``).
    Sonst wie bisher das 30-Minuten-Fenster ueber
    ``sensor_reading.attached_backplate`` (``source="window"``), und der
    Pool-Pfad bleibt damit unberuehrt.

    ``frames_in_window`` und ``last_seen`` behalten in **beiden** Faellen
    ihre Bedeutung: sie beschreiben das Fenster, nicht das Urteil. Das ist
    Absicht — die Detailseite zeigt sie als Diagnose, und bei einem sticky
    Geraet ist die interessante Frage gerade "was meldet der Taster
    eigentlich, obwohl das Urteil schon feststeht".

    Datenquelle ist dieselbe wie fuer Engine-Layer-4-Detached, aber als
    reine Lese-Aggregation (kein Engine-Pfad, kein Cache).
    """

    status: Literal["active", "inactive"] = Field(
        ...,
        description=(
            "Das Urteil. active = montiert. Quelle steht in ``source``: "
            "entweder der Montage-Nachweis oder mindestens ein True-Frame im Fenster."
        ),
    )
    source: Literal["mounted_confirmed", "window"] = Field(
        ...,
        description=(
            "Woraus ``status`` gebildet wurde. mounted_confirmed = "
            "``device.mounted_confirmed_at`` (zugeordnetes Geraet, Sprint 20e); "
            "window = das ``window_minutes``-Fenster ueber attached_backplate."
        ),
    )
    mounted_confirmed_at: datetime | None = Field(
        default=None,
        description=(
            "Zeitpunkt des Montage-Nachweises (erster Frame mit attached_backplate=true "
            "UND valve_position > 0). None bei Pool-Geraeten und bis zum ersten Beleg."
        ),
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
