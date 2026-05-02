"""Hotel-globale Konfiguration als Singleton-Tabelle (AE-28).

Genau **eine** Row mit ``id = 1``. CHECK-Constraint auf DB-Ebene verhindert
weitere Rows. Das ist bewusst nicht EAV — typsicher, migrationsfaehig,
explizit.

Bei Multi-Hotel-Mandantenfaehigkeit (Strategie A3, Phase 2) wird die
Singleton-CHECK durch ``hotel_id PK`` ersetzt. Migrationspfad sauber.

Sommermodus (``summer_mode_*``-Spalten) wird von der Engine in Layer 0
ausgewertet (AE-31, AE-34). Wenn aktiv: alle Raeume bekommen Frostschutz,
keine anderen Regeln greifen.
"""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    String,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base


class GlobalConfig(Base):
    __tablename__ = "global_config"

    # Singleton-PK: immer 1, durch CHECK erzwungen.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)

    # Hotel-Stammdaten
    hotel_name: Mapped[str] = mapped_column(String(200), nullable=False, default="Hotel")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Europe/Vienna")

    # Standard-Zeiten (Engine nutzt diese als Default fuer Vorheizen/Auszug)
    default_checkin_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(14, 0))
    default_checkout_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(11, 0))

    # Sommermodus (Layer 0 in der Engine)
    summer_mode_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summer_mode_starts_on: Mapped[date | None] = mapped_column(Date)
    summer_mode_ends_on: Mapped[date | None] = mapped_column(Date)

    # Alerts (Sprint 13 — Email-Service nutzt diese)
    alert_email: Mapped[str | None] = mapped_column(String(200))
    alert_device_offline_minutes: Mapped[int] = mapped_column(default=120, nullable=False)
    alert_battery_warn_percent: Mapped[int] = mapped_column(default=20, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Singleton-Erzwingung
        CheckConstraint("id = 1", name="ck_global_config_singleton"),
        # Sommermodus-Datums-Konsistenz wenn beide gesetzt
        CheckConstraint(
            "(summer_mode_starts_on IS NULL AND summer_mode_ends_on IS NULL)"
            " OR (summer_mode_starts_on IS NOT NULL AND summer_mode_ends_on IS NOT NULL"
            " AND summer_mode_starts_on <= summer_mode_ends_on)",
            name="ck_global_config_summer_dates",
        ),
        # Sinnvolle Bereiche
        CheckConstraint(
            "alert_device_offline_minutes >= 1 AND alert_device_offline_minutes <= 1440",
            name="ck_global_config_alert_offline_minutes",
        ),
        CheckConstraint(
            "alert_battery_warn_percent >= 1 AND alert_battery_warn_percent <= 100",
            name="ck_global_config_alert_battery",
        ),
    )
