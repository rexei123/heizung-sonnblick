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
    # Sprint 20 (AE-72): ``battery_percent`` ersetzt durch die Spannung. Die
    # Messwert-Tabelle der Geraeteseite zeigt damit "3,1 V" statt "65 %" —
    # der Prozentwert war aus einem 0.1-V-Raster interpoliert und im oberen
    # Bereich vom Codec gesaettigt (AE-64, §5.72). Bestandszeilen von vor
    # Migration 0024 haben ``None``; die Tabelle zeigt dort einen Strich.
    battery_voltage: Decimal | None = None
    rssi_dbm: int | None = None
    snr_db: Decimal | None = None
    open_window: bool | None = None
    attached_backplate: bool | None = None

    @field_serializer("temperature", "setpoint", "snr_db", "battery_voltage")
    def _decimal_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None
