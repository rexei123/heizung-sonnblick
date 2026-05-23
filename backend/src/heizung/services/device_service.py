"""Device-Lifecycle-Lese-Helper (Sprint 13b.1, AE-57).

Single Source of Truth fuer "aktive Devices"-Queries. Engine-Pfade
(``tasks/engine_tasks._get_devices_for_zone``,
``rules/engine.layer_device_detached``,
``rules/window_state.detect_open_window_zones``) sowie API-/CLI-
Listen-Endpoints filtern ueber diese Helper, nicht ueber Inline-
``Device.retired_at.is_(None)``-Klauseln.

Begruendung CLAUDE.md §5.58: verstreute Device-Queries mit unsicherem
Lifecycle-Filter sind S4-Verstoss-Kandidaten (doppelte Downlinks
waehrend Tausch-Race).

Helper liefert lifecycle-aktive Devices. Health-Filter (``healthy``)
und Room-Scope sind Caller-Verantwortung — siehe
``engine_tasks._get_devices_for_zone``, das ``health_state ==
'healthy'`` zusaetzlich filtert.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device


async def get_active_devices_for_zone(session: AsyncSession, zone_id: int) -> list[Device]:
    """Liefert aktive Devices einer HeatingZone (sortiert nach ``id`` ASC).

    Filter: ``heating_zone_id == zone_id AND retired_at IS NULL``.

    :param session: Async-Session, nicht committed durch diese Funktion.
    :param zone_id: Ziel-Zone-ID.
    :return: Liste von Device-Rows (kann leer sein).
    """
    stmt = (
        select(Device)
        .where(Device.heating_zone_id == zone_id)
        .where(Device.retired_at.is_(None))
        .order_by(Device.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_pool_devices(session: AsyncSession) -> list[Device]:
    """Liefert alle aktiven Pool-Devices (Reserve-Vickis).

    Filter: ``heating_zone_id IS NULL AND retired_at IS NULL``.
    Sortierung: ``created_at DESC`` (neueste zuerst — beim Tausch sieht
    Hotelier zuerst die juengst eingepairten Reserve-Geraete).

    :param session: Async-Session, nicht committed durch diese Funktion.
    :return: Liste von Pool-Device-Rows.
    """
    stmt = (
        select(Device)
        .where(Device.heating_zone_id.is_(None))
        .where(Device.retired_at.is_(None))
        .order_by(Device.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
