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
