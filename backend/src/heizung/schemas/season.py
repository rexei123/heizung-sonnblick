"""Pydantic-Schemas fuer Saison-API (Sprint 8, UI in Sprint 10)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeasonCreate(BaseModel):
    """Eingabe fuer POST /api/v1/seasons."""

    name: str = Field(..., min_length=1, max_length=100)
    starts_on: date
    ends_on: date
    is_active: bool = True
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _v_dates_ordered(self) -> SeasonCreate:
        if self.starts_on > self.ends_on:
            raise ValueError("starts_on darf nicht nach ends_on liegen")
        return self


class SeasonUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/seasons/{id}. Alle Felder optional."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)


class SeasonRead(BaseModel):
    """Ausgabe fuer GET /api/v1/seasons[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    starts_on: date
    ends_on: date
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
