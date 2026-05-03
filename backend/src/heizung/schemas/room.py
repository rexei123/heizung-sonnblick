"""Pydantic-Schemas fuer Zimmer-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from heizung.models.enums import Orientation, RoomStatus


class RoomCreate(BaseModel):
    """Eingabe fuer POST /api/v1/rooms."""

    number: str = Field(..., min_length=1, max_length=20, description="Zimmernummer (eindeutig)")
    display_name: str | None = Field(default=None, max_length=100)
    room_type_id: int = Field(..., gt=0)
    floor: int | None = Field(default=None, ge=-5, le=50)
    orientation: Orientation | None = None
    notes: str | None = Field(default=None, max_length=1000)


class RoomUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/rooms/{id}. Alle Felder optional.

    `status` ist hier zugaenglich, aber wird normal vom OccupancyService
    automatisch gesetzt. Manueller Eingriff fuer BLOCKED/CLEANING moeglich.
    """

    number: str | None = Field(default=None, min_length=1, max_length=20)
    display_name: str | None = Field(default=None, max_length=100)
    room_type_id: int | None = Field(default=None, gt=0)
    floor: int | None = Field(default=None, ge=-5, le=50)
    orientation: Orientation | None = None
    status: RoomStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)


class RoomRead(BaseModel):
    """Ausgabe fuer GET /api/v1/rooms[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    display_name: str | None
    room_type_id: int
    floor: int | None
    orientation: Orientation | None
    status: RoomStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime
