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
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings
from heizung.services.battery_health import battery_verdicts
from heizung.services.valve_health import valve_verdicts

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


async def count_valve_alerts(session: AsyncSession) -> tuple[int, int]:
    """Aktive Geraete mit Ventil-Hinweis: ``(klemmt_zu, zu_warm)``.

    **Getrennt gezaehlt und nicht summiert.** Die beiden Hinweise bedeuten
    verschiedene Handgriffe: "Ventil klemmt zu" heisst Ventil pruefen oder
    neu kalibrieren, "Zimmer zu warm" heisst nachsehen, ob der Kopf noch
    sitzt. Eine gemeinsame Zahl haette den Hausmeister losgeschickt, ohne
    ihm zu sagen, was er mitnehmen soll.

    Die Kachel zaehlt damit **genau** die Geraete, die auch ein Badge
    tragen — beides kommt aus ``valve_verdicts``, es gibt keine zweite
    Schwelle, die davon abdriften koennte. Dieselbe Invariante wie bei der
    Batterie.

    ``unbekannt`` zaehlt in keine der beiden Zahlen. Ein Geraet mit zu
    wenigen Messwerten ist kein Befund, sondern ein Geraet ohne Aussage —
    es gehoert auf die Offline-Achse, nicht hierher.

    Zwei Queries, unabhaengig von der Geraetezahl — kein N+1.
    Lifecycle-Filter ``retired_at IS NULL`` (§5.58).
    """
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.retired_at.is_(None))))
        .scalars()
        .all()
    )
    verdicts = await valve_verdicts(session, device_ids)
    klemmt = sum(1 for v in verdicts.values() if v.state == "ventil_klemmt_zu")
    warm = sum(1 for v in verdicts.values() if v.state == "zimmer_zu_warm")
    return klemmt, warm


async def count_battery_low(session: AsyncSession) -> int:
    """Anzahl aktiver Geraete (``retired_at IS NULL``) mit schwacher Batterie.

    Schwach = Batterie-Stufe ``warn`` oder ``kritisch`` (Sprint 20, AE-72).
    Die Kachel zaehlt damit **genau** die Geraete, die auch ein gelbes oder
    rotes Badge tragen — beides kommt aus ``battery_verdicts``, es gibt keine
    zweite Schwelle mehr, die davon abdriften koennte.

    Bis Sprint 19 stand hier ein Vergleich des juengsten
    ``battery_percent`` gegen ``alert_battery_warn_percent``, geklemmt gegen
    die fixe Kritisch-Grenze. Die Klemmung war noetig, weil die Warn-Schwelle
    konfigurierbar war und unter die Kritisch-Grenze gestellt werden konnte;
    mit festen Spannungs-Schwellen entfaellt der ganze Fall.

    Zwei Queries statt einer: erst die aktiven Geraete-IDs, dann ein
    Aggregat ueber deren 24-h-Fenster. Unabhaengig von der Geraetezahl —
    kein N+1.

    Lifecycle-Filter ``retired_at IS NULL`` (§5.58) bleibt.
    """
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.retired_at.is_(None))))
        .scalars()
        .all()
    )
    verdicts = await battery_verdicts(session, device_ids)
    return sum(1 for v in verdicts.values() if v.stage in ("warn", "kritisch"))
