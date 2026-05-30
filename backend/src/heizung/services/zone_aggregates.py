"""Sprint 14e FU-1 — Batch-Helper fuer Zone-Aggregat-Ist-Temperatur.

Liefert pro ``heating_zone_id`` den arithmetischen Mittelwert ueber die
juengsten Readings der **healthy + aktiven (``retired_at IS NULL``)** Vickis
einer Zone (AE-51 §4.1, §5.58). Reine Read-Aggregation auf vorhandenen
Tabellen — keine Schreib-Pfade, keine Engine-Kopplung.

Pattern ist parallel zu ``services.dashboard_aggregates._collect_zone_aggregates``
(Sprint 14c), aber per-Zone-ID-Filter statt Hotel-weitem Aggregat. Der reine
Mittelwert + Quantisierung lebt im Pure-Helper
``rules.aggregation.aggregate_zone_readings`` (eine Quelle der Wahrheit).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


async def latest_mean_temp_per_zone(
    session: AsyncSession,
    zone_ids: Iterable[int],
) -> dict[int, Decimal | None]:
    """Pro Zone den juengsten Ist-Temp-Mittelwert ueber healthy + aktive Vickis.

    Zwei Queries (R-D, kein N+1):

    1. ``Device`` mit ``retired_at IS NULL`` und ``heating_zone_id IN
       (zone_ids)`` — projiziert ``(id, heating_zone_id, health_state)``.
    2. Juengstes ``SensorReading`` pro Device via ``DISTINCT ON device_id``
       (Pattern aus ``dashboard_aggregates._collect_zone_aggregates``).

    Aggregation pro Zone delegiert an ``aggregate_zone_readings``
    (healthy-Filter + ``ROUND_HALF_EVEN`` auf 0.1 °C). Zonen ohne aktives
    Device tauchen mit ``None`` auf — Konsument muss alle erwarteten IDs
    selbst aus der Eingabe lesen, der Default-Pfad ist ``None``.
    """
    ids = list(zone_ids)
    if not ids:
        return {}

    device_rows = (
        await session.execute(
            select(Device.id, Device.heating_zone_id, Device.health_state)
            .where(Device.retired_at.is_(None))
            .where(Device.heating_zone_id.in_(ids))
        )
    ).all()
    if not device_rows:
        return dict.fromkeys(ids, None)

    device_ids = [row.id for row in device_rows]
    reading_rows = (
        await session.execute(
            select(
                SensorReading.device_id,
                SensorReading.temperature,
                SensorReading.open_window,
            )
            .where(SensorReading.device_id.in_(device_ids))
            .order_by(SensorReading.device_id, SensorReading.time.desc())
            .distinct(SensorReading.device_id)
        )
    ).all()
    latest: dict[int, tuple[Decimal | None, bool | None]] = {
        row.device_id: (row.temperature, row.open_window) for row in reading_rows
    }

    by_zone: dict[int, list[ReadingForAggregate]] = {zone_id: [] for zone_id in ids}
    for device_id, zone_id, health_state in device_rows:
        temp, open_window = latest.get(device_id, (None, None))
        by_zone[zone_id].append(
            ReadingForAggregate(
                temperature_c=temp,
                open_window=open_window,
                health_state=health_state,
            )
        )

    result: dict[int, Decimal | None] = {}
    for zone_id, readings in by_zone.items():
        mean_temp_c, _ = aggregate_zone_readings(readings)
        result[zone_id] = mean_temp_c
    return result
