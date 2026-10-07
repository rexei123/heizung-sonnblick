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
    # Sprint 15d (AE-65), Eingangsgroesse seit Sprint 20 die Spannung
    # (AE-72): aktive Geraete mit Batterie-Stufe ``warn`` oder ``kritisch``.
    #
    # Der Vermerk hier stand bis Sprint 20e auf "juengster battery_percent <
    # alert_battery_warn_percent". Beides gilt nicht mehr: die Stufe rechnet
    # auf dem 24-h-Median der Spannung, und die konfigurierbare
    # Prozent-Schwelle ist mit AE-72 entfallen (§5.77 — ein ueberholter
    # Vermerk wird wie ein Befund gelesen).
    battery_low_count: int
    # Sprint 20e (T7/T10): Ventil-Hinweise, getrennt gezaehlt. Siehe
    # ``dashboard_aggregates.count_valve_alerts`` fuer die Begruendung,
    # warum es zwei Zahlen sind und nicht eine.
    valve_stuck_count: int = 0
    room_too_warm_count: int = 0

    @field_serializer("avg_temperature_celsius")
    def _avg_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None
