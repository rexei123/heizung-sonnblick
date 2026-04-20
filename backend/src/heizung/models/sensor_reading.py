"""Zeitreihen-Messwerte von LoRaWAN-Geräten.

In der Migration wird die Tabelle zur TimescaleDB-Hypertable über
``time`` konvertiert. Dafür muss die Zeit-Spalte Teil des Primärschlüssels
sein.

Keine ``updated_at``/``created_at`` — Readings sind unveränderlich.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base


class SensorReading(Base):
    __tablename__ = "sensor_reading"

    # Composite PK (time, device_id): Timescale-Anforderung + natürlicher
    # Zugriffspfad.
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    device_id: Mapped[int] = mapped_column(
        ForeignKey("device.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    temperature: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    setpoint: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    valve_position: Mapped[int | None] = mapped_column(SmallInteger)  # 0..100 %
    battery_percent: Mapped[int | None] = mapped_column(SmallInteger)
    rssi_dbm: Mapped[int | None] = mapped_column(SmallInteger)
    snr_db: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))

    # Raw-Payload nur für Debugging/Audit. Große Volumina — ggf. später
    # in ein separates "cold" Schema auslagern.
    raw_payload: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("ix_sensor_reading_device_time", "device_id", "time"),
    )
