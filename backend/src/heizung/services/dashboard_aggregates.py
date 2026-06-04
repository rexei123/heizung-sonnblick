"""Sprint 14c — Hotel-Aggregat-Helper fuer das Dashboard (`/api/v1/dashboard/kpi`).

Sechs read-only Aggregat-Funktionen ueber den gesamten Hotelbestand. Bewusst
duenn: jede liefert genau den Wert einer KPI-Kachel. Keine Schreib-Pfade, keine
Engine-Kopplung.

Konventionen:
- **Decimal** fuer Temperatur-Aggregate, ``ROUND_HALF_EVEN`` auf 0.1 °C
  (User-Regel + Konsistenz zu ``rules.aggregation``).
- **Lifecycle-Filter** ``Device.retired_at IS NULL`` fuer alle Device-Queries
  (CLAUDE §5.58).
- **Zone-Aggregat** wird ueber den Bestand-Helper
  ``rules.aggregation.aggregate_zone_readings`` berechnet (healthy-Filter +
  OR-Fenster + Mittelwert leben dort, eine Quelle der Wahrheit, AE-51 §4.1).
- **Engine-Tick-Marker** ist ``EventLogLayer.HARD_CLAMP`` — laeuft in beiden
  Pfaden (normal + Sommer-Fast-Path, ``engine.py``) und schliesst die
  Off-Pipeline-Inseln ``MANUAL_OVERRIDE_BLOCKED`` (synthetische ``evaluation_id``,
  §5.52) aus.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import EventLogLayer, RoomStatus
from heizung.models.event_log import EventLog
from heizung.models.global_config import GlobalConfig
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings
from heizung.services.battery_health import DEFAULT_BATTERY_WARN_PCT

_ONLINE_STATES = ("healthy", "degraded")
_QUANT_TENTH: Decimal = Decimal("0.1")


async def count_rooms_occupied(session: AsyncSession) -> tuple[int, int]:
    """``(belegt, gesamt)``. Belegt = ``Room.status == OCCUPIED``.

    Quelle ist das persistierte ``Room.status`` (vom ``sync_room_status``-Cron
    aus aktiven Occupancies abgeleitet, §5.53). Fuer eine Uebersichts-Kachel
    ist die Sync-Latenz akzeptabel.
    """
    occupied = (
        await session.execute(
            select(func.count()).select_from(Room).where(Room.status == RoomStatus.OCCUPIED)
        )
    ).scalar_one()
    total = (await session.execute(select(func.count()).select_from(Room))).scalar_one()
    return occupied, total


async def count_devices_online(session: AsyncSession) -> tuple[int, int]:
    """``(online, gesamt_aktiv)``. Online = ``health_state IN (healthy, degraded)``.

    Beide Counts mit Lifecycle-Filter ``retired_at IS NULL`` (§5.58).
    """
    online = (
        await session.execute(
            select(func.count())
            .select_from(Device)
            .where(Device.retired_at.is_(None))
            .where(Device.health_state.in_(_ONLINE_STATES))
        )
    ).scalar_one()
    total = (
        await session.execute(
            select(func.count()).select_from(Device).where(Device.retired_at.is_(None))
        )
    ).scalar_one()
    return online, total


async def count_active_overrides(session: AsyncSession) -> int:
    """Aktive Overrides = ``revoked_at IS NULL AND expires_at > now()``."""
    now = datetime.now(tz=UTC)
    return (
        await session.execute(
            select(func.count())
            .select_from(ManualOverride)
            .where(ManualOverride.revoked_at.is_(None))
            .where(ManualOverride.expires_at > now)
        )
    ).scalar_one()


async def last_engine_tick(session: AsyncSession) -> datetime | None:
    """Zeitpunkt der juengsten abgeschlossenen Engine-Evaluation (UTC).

    ``MAX(time)`` ueber ``event_log`` gefiltert auf ``layer = 'hard_clamp'``.
    ``None`` wenn noch nie ein Tick lief.
    """
    return cast(
        "datetime | None",
        (
            await session.execute(
                select(func.max(EventLog.time)).where(EventLog.layer == EventLogLayer.HARD_CLAMP)
            )
        ).scalar_one(),
    )


async def _collect_zone_aggregates(
    session: AsyncSession,
) -> list[tuple[Decimal | None, bool | None]]:
    """Pro Zone ``(mean_temp_c, any_open_window)`` ueber healthy Vickis.

    Laedt aktive Devices (``retired_at IS NULL``) mit Zone-Zuordnung und das
    juengste Reading pro Device (DISTINCT ON, eine indizierte Query), gruppiert
    nach Zone und delegiert die Aggregation an ``aggregate_zone_readings``
    (healthy-Filter dort). Zonen ohne Device tauchen nicht auf.
    """
    device_rows = (
        await session.execute(
            select(Device.id, Device.heating_zone_id, Device.health_state)
            .where(Device.retired_at.is_(None))
            .where(Device.heating_zone_id.is_not(None))
        )
    ).all()
    if not device_rows:
        return []

    # Juengstes Reading pro Device in einer Query (DISTINCT ON device_id).
    reading_rows = (
        await session.execute(
            select(
                SensorReading.device_id,
                SensorReading.temperature,
                SensorReading.open_window,
            )
            .order_by(SensorReading.device_id, SensorReading.time.desc())
            .distinct(SensorReading.device_id)
        )
    ).all()
    latest: dict[int, tuple[Decimal | None, bool | None]] = {
        row.device_id: (row.temperature, row.open_window) for row in reading_rows
    }

    by_zone: dict[int, list[ReadingForAggregate]] = {}
    for device_id, zone_id, health_state in device_rows:
        temp, open_window = latest.get(device_id, (None, None))
        by_zone.setdefault(zone_id, []).append(
            ReadingForAggregate(
                temperature_c=temp,
                open_window=open_window,
                health_state=health_state,
            )
        )

    return [aggregate_zone_readings(readings) for readings in by_zone.values()]


async def avg_room_temperature(session: AsyncSession) -> Decimal | None:
    """Mittelwert ueber die Zonen-Aggregate aller Zonen mit healthy Vickis.

    Mittelt die per-Zone-Mittelwerte (jede Zone gleich gewichtet), quantisiert
    auf 0.1 °C mit ``ROUND_HALF_EVEN``. ``None`` wenn keine Zone einen
    healthy-Temperatur-Wert liefert.
    """
    zone_means = [mean for mean, _ in await _collect_zone_aggregates(session) if mean is not None]
    if not zone_means:
        return None
    mean = sum(zone_means, start=Decimal("0")) / Decimal(len(zone_means))
    return mean.quantize(_QUANT_TENTH, rounding=ROUND_HALF_EVEN)


async def count_zones_window_open(session: AsyncSession) -> int:
    """Anzahl Zonen mit ``open_window=True`` (OR ueber healthy Vickis der Zone)."""
    return sum(1 for _, window in await _collect_zone_aggregates(session) if window is True)


async def count_battery_low(session: AsyncSession) -> int:
    """Anzahl aktiver Geraete (``retired_at IS NULL``) mit schwacher Batterie.

    Schwach = juengster ``battery_percent`` < ``alert_battery_warn_percent``
    (Default 20, GlobalConfig-Singleton). Faengt warn UND kritisch in einem
    Count (alles unter der Warn-Schwelle), konsistent mit der Batterie-Health-
    Achse aus Sprint 15d (AE-65). ``battery_percent IS NULL`` zaehlt nicht
    (kein ``< threshold``-Match).

    Effizienz: juengstes Reading je Geraet via ``DISTINCT ON device_id`` ueber
    ``ix_sensor_reading_device_time`` (gleiches Muster wie
    ``_collect_zone_aggregates`` / 15b/15c). Lifecycle-Filter ``retired_at IS
    NULL`` (§5.58) am Device-Join.
    """
    gc = await session.get(GlobalConfig, 1)
    threshold = gc.alert_battery_warn_percent if gc is not None else DEFAULT_BATTERY_WARN_PCT

    latest = (
        select(SensorReading.device_id, SensorReading.battery_percent)
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
        .subquery()
    )
    stmt = (
        select(func.count())
        .select_from(Device)
        .join(latest, latest.c.device_id == Device.id)
        .where(Device.retired_at.is_(None))
        .where(latest.c.battery_percent.is_not(None))
        .where(latest.c.battery_percent < threshold)
    )
    return (await session.execute(stmt)).scalar_one()
