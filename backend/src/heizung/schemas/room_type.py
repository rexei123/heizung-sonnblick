"""Pydantic-Schemas fuer Raumtypen-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RoomTypeCreate(BaseModel):
    """Eingabe fuer POST /api/v1/room-types."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_bookable: bool = True

    default_t_occupied: Decimal = Field(
        default=Decimal("21.0"), description="Standardtemperatur belegt (°C)"
    )
    default_t_vacant: Decimal = Field(
        default=Decimal("18.0"), description="Standardtemperatur frei (°C)"
    )
    default_t_night: Decimal = Field(
        default=Decimal("19.0"), description="Standardtemperatur nachts (°C)"
    )

    # Optionale Override-Grenzen (NULL = greift globaler Default)
    max_temp_celsius: Decimal | None = Field(
        default=None, description="Obere Override-Grenze fuer diesen Raumtyp"
    )
    min_temp_celsius: Decimal | None = Field(
        default=None, description="Untere Override-Grenze fuer diesen Raumtyp"
    )
    treat_unoccupied_as_vacant_after_hours: int | None = Field(
        default=None, ge=1, le=240, description="Override fuer R7 (Langzeit-Absenkung)"
    )

    @field_validator(
        "default_t_occupied",
        "default_t_vacant",
        "default_t_night",
        "max_temp_celsius",
        "min_temp_celsius",
    )
    @classmethod
    def _v_temp_range(cls, v: Decimal | None) -> Decimal | None:
        # Erlaubter Bereich plausibel fuer Hotel-Heizung. DB-Constraint
        # auf manual_setpoint_event ist 5-30 °C; analog hier.
        if v is None:
            return v
        if v < Decimal("5.0") or v > Decimal("30.0"):
            raise ValueError("Temperatur muss zwischen 5.0 und 30.0 °C liegen")
        return v

    @model_validator(mode="after")
    def _v_min_max_consistency(self) -> RoomTypeCreate:
        if (
            self.min_temp_celsius is not None
            and self.max_temp_celsius is not None
            and self.min_temp_celsius >= self.max_temp_celsius
        ):
            raise ValueError("min_temp_celsius muss kleiner als max_temp_celsius sein")
        return self


class RoomTypeUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/room-types/{id}. Alle Felder optional."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_bookable: bool | None = None

    default_t_occupied: Decimal | None = None
    default_t_vacant: Decimal | None = None
    default_t_night: Decimal | None = None

    max_temp_celsius: Decimal | None = None
    min_temp_celsius: Decimal | None = None
    treat_unoccupied_as_vacant_after_hours: int | None = Field(default=None, ge=1, le=240)

    @field_validator(
        "default_t_occupied",
        "default_t_vacant",
        "default_t_night",
        "max_temp_celsius",
        "min_temp_celsius",
    )
    @classmethod
    def _v_temp_range(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return v
        if v < Decimal("5.0") or v > Decimal("30.0"):
            raise ValueError("Temperatur muss zwischen 5.0 und 30.0 °C liegen")
        return v


class RoomTypeRead(BaseModel):
    """Ausgabe fuer GET /api/v1/room-types[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    is_bookable: bool
    default_t_occupied: Decimal
    default_t_vacant: Decimal
    default_t_night: Decimal
    max_temp_celsius: Decimal | None
    min_temp_celsius: Decimal | None
    treat_unoccupied_as_vacant_after_hours: int | None
    created_at: datetime
    updated_at: datetime
