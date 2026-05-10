"""Zeitreihen-Messwerte von LoRaWAN-Geräten.

In der Migration wird die Tabelle zur TimescaleDB-Hypertable über
``time`` konvertiert. Dafür muss die Zeit-Spalte Teil des Primärschlüssels
sein.

Keine ``updated_at``/``created_at`` — Readings sind unveränderlich.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
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

    # LoRaWAN Frame Counter — fuer idempotenten MQTT-Replay-Schutz
    # (UNIQUE auf (time, device_id, fcnt) plus ON CONFLICT DO NOTHING im Subscriber).
    # Nullable, weil Bestandsdaten aus Sprint 0/2 keinen fcnt hatten.
    fcnt: Mapped[int | None] = mapped_column(Integer)

    temperature: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    setpoint: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    valve_position: Mapped[int | None] = mapped_column(SmallInteger)  # 0..100 %
    battery_percent: Mapped[int | None] = mapped_column(SmallInteger)
    rssi_dbm: Mapped[int | None] = mapped_column(SmallInteger)
    snr_db: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))

    # Sprint 9.10: Vicki-Codec-Feld ``openWindow`` aus Periodic-Reports.
    # NULL = Feld nicht im Payload vorhanden (alter Codec / Recovery-Daten),
    # NICHT identisch mit False. Layer 4 behandelt NULL + False gleich.
    open_window: Mapped[bool | None] = mapped_column(Boolean)

    # Sprint 9.11x: Vicki-Codec-Feld ``attachedBackplate`` (FW >= 4.1).
    # True = Vicki an Wandhalterung angeflanscht, False = demontiert.
    # NULL = Feld nicht im Payload vorhanden (alter Codec). Layer 4
    # Detached-Trigger fordert AND-Semantik ueber alle Devices der Zone:
    # NULL zaehlt als "unklar" (Device blockt den Trigger), False alleine
    # reicht nicht — beide letzten frischen Frames muessen False sein.
    attached_backplate: Mapped[bool | None] = mapped_column(Boolean)

    # Raw-Payload nur für Debugging/Audit. Große Volumina — ggf. später
    # in ein separates "cold" Schema auslagern.
    raw_payload: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("ix_sensor_reading_device_time", "device_id", "time"),)
