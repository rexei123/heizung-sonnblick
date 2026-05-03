"""Pydantic-Schemas fuer Heizzone-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from heizung.models.enums import HeatingZoneKind


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
    created_at: datetime
    updated_at: datetime
