"""Pydantic-Schemas fuer Heizzone-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from heizung.models.enums import HeatingZoneKind, OverrideSource


class ZoneActiveOverrideRead(BaseModel):
    """Sprint 14d FU-5: aktiver Override der Zone (read-only).

    Spiegelt ``DeviceActiveOverrideRead`` (schemas/device.py) — gleiche Form,
    damit der Frontend-Type wiederverwendbar ist. ``setpoint_celsius`` als
    ``field_serializer``->``float`` (JSON-Zahl, §5.63-Konvention),
    ``expires_at`` UTC (Frontend lokalisiert, §5.65).
    """

    source: OverrideSource
    setpoint_celsius: Decimal
    started_at: datetime
    expires_at: datetime

    @field_serializer("setpoint_celsius")
    def _decimal_to_float(self, v: Decimal) -> float:
        return float(v)


class HeatingZoneCreate(BaseModel):
    """Eingabe fuer POST /api/v1/rooms/{room_id}/heating-zones."""

    kind: HeatingZoneKind
    name: str = Field(..., min_length=1, max_length=100)
    is_towel_warmer: bool = False


class HeatingZoneUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/rooms/{room_id}/heating-zones/{zone_id}."""

    kind: HeatingZoneKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_towel_warmer: bool | None = None


class HeatingZoneRead(BaseModel):
    """Ausgabe fuer GET /api/v1/rooms/{room_id}/heating-zones."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    kind: HeatingZoneKind
    name: str
    is_towel_warmer: bool
    health_state: Literal["healthy", "degraded", "silent", "no_device"]
    created_at: datetime
    updated_at: datetime

    # Sprint 14d FU-5: aktiver Zone-Override (Zone-Match + Room-Scope-Fallback,
    # ``override_service.get_active``). Default None; die Zone-Endpoints
    # (list/get) befuellen ihn per-Zone via model_copy. Ersetzt den
    # ``useZoneOverride``-Roundtrip in ZoneCard.
    active_override: ZoneActiveOverrideRead | None = None

    # Sprint 14e FU-1: Zone-Aggregat-Ist-Temperatur ueber healthy + aktive Vickis
    # (AE-51 §4.1). Default None; die Zone-Endpoints befuellen ihn via Batch-
    # Enrich (``services/zone_aggregates.latest_mean_temp_per_zone``) mit dem
    # Pure-Helper ``rules.aggregation.aggregate_zone_readings``. None wenn keine
    # healthy Vicki mit Temperatur in der Zone.
    mean_temperature_c: Decimal | None = None

    # Sprint 24d: **wann** dieser Mittelwert gemessen wurde.
    #
    # Der Anlass ist ein Befund des Betreibers vom 24.10.2026: die Karte
    # zeigte „—", weil die Abfrage die juengste Zeile je Geraet nahm — und
    # eine Befehlsantwort fuehrt keine Temperatur. Der Filter sitzt jetzt
    # in der Abfrage; der Zeitstempel steht daneben, damit ein alter
    # Messwert als alter zu erkennen ist und nicht als aktueller.
    mean_temperature_at: datetime | None = None

    # Sprint 24d: was der Zone fehlt, falls ihr etwas fehlt.
    #
    # ``health_state == "no_device"`` sagte „Kein Geraet" auch dort, wo
    # ein Fuehler zugeordnet ist und nur das Stellglied fehlt (Befund des
    # Betreibers, 24.10.2026). Das Kennzeichen hatte recht und sagte das
    # Falsche — es liess nach einer Zuordnung suchen, die gerade gemacht
    # worden war. ``None`` heisst: nichts fehlt.
    geraete_luecke: Literal["kein_fuehler", "kein_stellglied", "beides"] | None = None

    # Sprint 14e FU-2: zuletzt von der Engine als HARD_CLAMP-Setpoint geschriebener
    # Wert fuer das Zimmer dieser Zone (AE-55 P1; alle Zonen eines Zimmers teilen
    # den Wert, AE-51 §4.2). Quelle: ``event_log.setpoint_out`` der juengsten
    # HARD_CLAMP-Row im 1h-Fenster. Default None; befuellt via
    # ``services/event_log_service.latest_hard_clamp_setpoint_per_room``.
    engine_setpoint_c: Decimal | None = None

    @field_serializer("mean_temperature_c", "engine_setpoint_c")
    def _decimal_temp_to_float(self, v: Decimal | None) -> float | None:
        # §5.63: Decimal -> JSON-Zahl. Symmetrisch zur Override-Setpoint-Serialisierung.
        return None if v is None else float(v)
