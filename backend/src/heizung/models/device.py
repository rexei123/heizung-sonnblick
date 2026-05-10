"""Gerät (Thermostat oder Sensor).

Herstellerunabhängige Abstraktion: nur LoRaWAN-Identifikation, Typ und
Zuordnung zur Heizzone. Die konkrete Protokoll-Implementierung liegt in
``heizung.drivers`` und greift über ``dev_eui`` auf das Gerät zu.

Keys (AppKey, NwkKey) werden NICHT hier gespeichert, sondern verschlüsselt
in einer späteren Tabelle oder per ChirpStack verwaltet.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import DeviceKind, DeviceVendor, _enum_values

if TYPE_CHECKING:
    from heizung.models.heating_zone import HeatingZone


class Device(Base):
    __tablename__ = "device"

    id: Mapped[int] = mapped_column(primary_key=True)

    # LoRaWAN-Identifikation (8 Byte hex = 16 Zeichen).
    dev_eui: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    app_eui: Mapped[str | None] = mapped_column(String(16))

    kind: Mapped[DeviceKind] = mapped_column(
        SQLEnum(
            DeviceKind,
            name="device_kind",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    vendor: Mapped[DeviceVendor] = mapped_column(
        SQLEnum(
            DeviceVendor,
            name="device_vendor",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String(50), nullable=False)

    # Zuordnung zur Zone. NULL, solange das Gerät physisch vorhanden aber
    # noch keiner Zone zugeteilt ist (Provisioning).
    heating_zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("heating_zone.id", ondelete="SET NULL")
    )

    label: Mapped[str | None] = mapped_column(String(200))

    # Sprint 9.11x: Schema-Vorbereitung fuer 9.11x.b (Codec-Drift-Schutz).
    # In 9.11x ungenutzt, in 9.11x.b vom MQTT-Subscriber gepflegt.
    firmware_version: Mapped[str | None] = mapped_column(String(8), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    heating_zone: Mapped[HeatingZone | None] = relationship(back_populates="devices")
