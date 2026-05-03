"""Pydantic-Schemas fuer Belegungs-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heizung.models.enums import OccupancySource


class OccupancyCreate(BaseModel):
    """Eingabe fuer POST /api/v1/occupancies."""

    room_id: int = Field(..., gt=0)
    check_in: datetime = Field(..., description="Anreisedatum + Uhrzeit (timezone-aware)")
    check_out: datetime = Field(..., description="Abreisedatum + Uhrzeit (timezone-aware)")
    guest_count: int | None = Field(default=None, ge=1, le=20)
    source: OccupancySource = OccupancySource.MANUAL
    external_id: str | None = Field(
        default=None, max_length=100, description="PMS-Reservierungsnummer (optional)"
    )

    @model_validator(mode="after")
    def _v_dates_ordered(self) -> OccupancyCreate:
        if self.check_in >= self.check_out:
            raise ValueError("check_in muss vor check_out liegen")
        return self


class OccupancyCancel(BaseModel):
    """Eingabe fuer PATCH /api/v1/occupancies/{id} (Storno).

    Sprint 8 erlaubt nur Stornieren via PATCH, keine Daten-Aenderung.
    Storno setzt is_active=False + cancelled_at=NOW.
    """

    cancel: bool = Field(..., description="Muss true sein, sonst kein Effekt")


class OccupancyRead(BaseModel):
    """Ausgabe fuer GET /api/v1/occupancies[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    check_in: datetime
    check_out: datetime
    guest_count: int | None
    source: OccupancySource
    external_id: str | None
    is_active: bool
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
