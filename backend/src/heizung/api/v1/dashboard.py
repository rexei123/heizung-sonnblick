"""Dashboard-KPI-API (Sprint 14c).

    GET /api/v1/dashboard/kpi  -> DashboardKpiRead

Liefert die 6 Uebersichts-Kacheln der Startseite ``/`` in einem Request.
Read-only, ``require_user`` (Admin + Mitarbeiter). Die Aggregate leben in
``services.dashboard_aggregates`` (eine Funktion pro KPI).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_user
from heizung.db import get_session
from heizung.models.user import User
from heizung.schemas.dashboard import DashboardKpiRead
from heizung.services import dashboard_aggregates as agg

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/kpi",
    response_model=DashboardKpiRead,
    summary="Hotel-KPIs fuer das Dashboard (6 Kacheln)",
)
async def get_dashboard_kpi(
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> DashboardKpiRead:
    rooms_occupied, rooms_total = await agg.count_rooms_occupied(session)
    devices_online, devices_total = await agg.count_devices_online(session)
    return DashboardKpiRead(
        rooms_occupied=rooms_occupied,
        rooms_total=rooms_total,
        avg_temperature_celsius=await agg.avg_room_temperature(session),
        devices_online=devices_online,
        devices_total=devices_total,
        active_overrides=await agg.count_active_overrides(session),
        zones_window_open=await agg.count_zones_window_open(session),
        last_engine_tick=await agg.last_engine_tick(session),
    )
