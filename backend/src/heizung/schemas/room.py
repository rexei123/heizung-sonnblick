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
    guest_override_blocked: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime

    # Sprint 14d (R-A): Bool-Indikator „Zimmer hat >= 1 aktive Uebersteuerung"
    # fuer die Zimmer-Liste. Default False; NUR der Listen-Endpoint
    # (``list_rooms``) befuellt ihn via Batch-Aggregat
    # (``override_service.get_rooms_with_active_override``). Einzel-/Write-
    # Responses (get/create/update) lassen ihn auf False — dort nicht
    # konsumiert (RoomTable liest ausschliesslich die Liste).
    has_active_override: bool = False


class RoomOverrideBlockUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/rooms/{id}/override-block-state (Sprint 12c).

    Eigener Endpoint statt Erweiterung von ``RoomUpdate``: Toggle hat
    eigene Audit-Action und Auto-Revoke-Semantik (siehe AE-58 Sprint 12c).
    """

    model_config = ConfigDict(extra="forbid")

    blocked: bool
