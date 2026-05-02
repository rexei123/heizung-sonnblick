"""Pydantic-Schemas fuer manuelle Setpoint-Aktionen (Sprint 8 Tabelle, UI Sprint 10)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heizung.models.enums import ManualOverrideScope


class ManualSetpointEventCreate(BaseModel):
    """Eingabe fuer POST /api/v1/manual-setpoint-events.

    "Temperatur jetzt setzen" - one-off-Aktion mit Zeitbegrenzung. Wirkt
    in Engine-Layer 3a (manual_override).
    """

    scope: ManualOverrideScope
    room_type_id: int | None = Field(default=None, gt=0)
    room_id: int | None = Field(default=None, gt=0)
    target_setpoint_celsius: Decimal = Field(..., description="Soll-Temperatur (5.0 - 30.0 °C)")
    starts_at: datetime | None = Field(default=None, description="Default = jetzt (Server-NOW)")
    ends_at: datetime
    reason: str = Field(..., min_length=1, max_length=500)

    @model_validator(mode="after")
    def _v_scope_consistency(self) -> ManualSetpointEventCreate:
        if self.scope == ManualOverrideScope.ROOM_TYPE and (
            self.room_type_id is None or self.room_id is not None
        ):
            raise ValueError("scope=room_type braucht room_type_id und kein room_id")
        if self.scope == ManualOverrideScope.ROOM and (
            self.room_id is None or self.room_type_id is not None
        ):
            raise ValueError("scope=room braucht room_id und kein room_type_id")
        return self

    @model_validator(mode="after")
    def _v_temp_range(self) -> ManualSetpointEventCreate:
        # DB-Constraint ist 5.0 - 30.0; hier 1:1.
        if self.target_setpoint_celsius < Decimal("5.0") or self.target_setpoint_celsius > Decimal(
            "30.0"
        ):
            raise ValueError("target_setpoint_celsius muss zwischen 5.0 und 30.0 °C liegen")
        return self

    @model_validator(mode="after")
    def _v_time_window(self) -> ManualSetpointEventCreate:
        if self.starts_at is not None and self.starts_at >= self.ends_at:
            raise ValueError("starts_at muss vor ends_at liegen")
        return self


class ManualSetpointEventCancel(BaseModel):
    """Eingabe fuer PATCH /api/v1/manual-setpoint-events/{id} (Storno)."""

    cancel: bool = Field(..., description="Muss true sein")


class ManualSetpointEventRead(BaseModel):
    """Ausgabe fuer GET /api/v1/manual-setpoint-events[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scope: ManualOverrideScope
    room_type_id: int | None
    room_id: int | None
    target_setpoint_celsius: Decimal
    starts_at: datetime
    ends_at: datetime
    reason: str
    is_active: bool
    cancelled_at: datetime | None
    created_at: datetime
