"""Sprint 14c — Dashboard-KPI-Schema (`GET /api/v1/dashboard/kpi`).

Ein flaches Read-Schema fuer die 6 Uebersichts-Kacheln auf ``/``. Additiv
erweiterbar (B-14c-FU-1: PMS-/Wetter-Kacheln nach Sprint 16a) ohne Bruch.

``avg_temperature_celsius`` wird als ``field_serializer``->``float`` ausgegeben
(Konvention wie ``DeviceActiveOverrideRead`` / ``SensorReadingRead``), damit der
Frontend-Zod-Spiegel eine JSON-Zahl erhaelt (§5.63). ``last_engine_tick`` ist
UTC ISO-8601 — das Frontend lokalisiert (Europe/Vienna, §5.65).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer


class DashboardKpiRead(BaseModel):
    """Aggregierte Hotel-KPIs fuer das Dashboard."""

    model_config = ConfigDict(from_attributes=True)

    rooms_occupied: int
    rooms_total: int
    avg_temperature_celsius: Decimal | None
    devices_online: int
    devices_total: int
    active_overrides: int
    zones_window_open: int
    last_engine_tick: datetime | None
    # Sprint 15d (AE-65): aktive Geraete mit schwacher Batterie (juengster
    # battery_percent < alert_battery_warn_percent). Additiv, die bestehenden
    # KPI-Felder bleiben unveraendert.
    battery_low_count: int

    @field_serializer("avg_temperature_celsius")
    def _avg_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None
