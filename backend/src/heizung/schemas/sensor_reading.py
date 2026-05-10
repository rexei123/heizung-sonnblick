"""Pydantic-Schemas fuer SensorReading-API-Responses."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


class SensorReadingRead(BaseModel):
    """Ein einzelner SensorReading-Datensatz fuer die REST-API."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    fcnt: int | None = None
    temperature: Decimal | None = None
    setpoint: Decimal | None = None
    valve_position: int | None = None
    battery_percent: int | None = None
    rssi_dbm: int | None = None
    snr_db: Decimal | None = None

    @field_serializer("temperature", "setpoint", "snr_db")
    def _decimal_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None
