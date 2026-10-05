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

    # Sprint 20 (AE-72): Geraete-Spannung aus dem Codec-Feld
    # ``battery_voltage`` (mclimate-vicki.js:142), Raster 0.1 V. Seit
    # Migration 0024 die Quelle der drei Batterie-Stufen — ``battery_percent``
    # bleibt als Rueckfallpfad bestehen, hat aber keinen Konsumenten mehr.
    #
    # NULL = kein Spannungswert fuer diese Zeile (Bestandsdaten vor 0024,
    # Frame ohne das Feld), NICHT 0.0 V. Die Bewertung zaehlt NULL nicht mit.
    #
    # Decimal, nicht Float: der Schwellen-Vergleich laeuft exakt auf dem
    # 0.1-V-Raster, und 2.9 hat in IEEE-754 keine exakte Darstellung.
    battery_voltage: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))

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

    # Sprint 19 (PR B): Vicki-Codec-Feld ``brokenSensor`` — Bit 0 des
    # Low-Nibbles von Byte 7 (mclimate-vicki.js:161). Der Codec liefert es
    # seit je her, persistiert wurde es bis Migration 0023 nicht.
    #
    # Der Eingangstest urteilt ueber die Ventilstellung, und die Vicki regelt
    # gegen ihren internen Temperatursensor. Meldet der einen Defekt, ist die
    # Aussage ueber das Ventil wertlos — das Geraet regelt gegen einen
    # Messwert, dem es selbst nicht traut.
    #
    # NULL = Feld nicht im Payload (alter Codec), NICHT identisch mit False.
    # Nur True ist ein Defekt-Befund.
    broken_sensor: Mapped[bool | None] = mapped_column(Boolean)

    # Sprint 20f (T7, Migration 0025): Vicki ``calibrationFailed``
    # (``status8 & 0x40``). Der Codec setzt das Bit seit Sprint 6.8 und es
    # wurde bis hierher bei jedem Frame verworfen.
    #
    # Warum es zaehlt: ein Geraet mit fehlgeschlagener Kalibrierung fuehrt
    # das Ventil nicht richtig. Der Eingangstest urteilt ueber die
    # Ventilstellung und faellt es durch, ohne den Grund nennen zu koennen —
    # mit dem Bit heisst derselbe Befund "Kalibrierung fehlgeschlagen" und
    # ist ein Handgriff am Geraet (Cmd 0x03) statt einer Fehlersuche.
    # Erster belegter Fall: Geraet 026 am 05.10.2026 (``status8 = 0x70``).
    #
    # NULL = Feld nicht im Payload, NICHT identisch mit False. Nur True ist
    # ein Befund — dieselbe Drei-Zustands-Regel wie bei ``open_window``,
    # ``attached_backplate`` und ``broken_sensor``.
    calibration_failed: Mapped[bool | None] = mapped_column(Boolean)

    # Raw-Payload nur für Debugging/Audit. Große Volumina — ggf. später
    # in ein separates "cold" Schema auslagern.
    raw_payload: Mapped[str | None] = mapped_column(String)

    __table_args__ = (Index("ix_sensor_reading_device_time", "device_id", "time"),)
