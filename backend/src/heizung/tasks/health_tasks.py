"""Sprint 11 T5 — Periodische Health-State-Berechnung (AE-53).

Celery-Beat triggert ``compute_health_state`` alle 5 min. Pro Device:
1. Basis-State aus ``last_uplink_age`` (MAX(sensor_reading.time)):
   - ``<= 2h`` healthy / ``2-24h`` degraded / ``> 24h`` silent / kein
     Reading => silent
2. Outlier-Check vs. Zone-Median (nur wenn Basis healthy UND Zone hat
   >= 2 weitere healthy-Devices mit frischem Reading): bei
   ``|device_temp - zone_median| > 7.0`` => suspicious.
3. Implausible-Counter aus Redis (Schwelle 10) => silent (Stufe-3-
   Trigger). Redis-Offline => Counter als 0 behandelt (defensive S5).

Pro Zone wird der Health-State aus den Device-States abgeleitet
(no_device / silent / degraded / healthy).

Beim Uebergang ``previous != silent`` -> ``new == silent`` wird ein
Eintrag in ``silent_transitions`` gesammelt (Mail-Stub-Input fuer T6).

Idempotenz: Wert-Vergleich vor Write (SQLAlchemy-Attribut-Tracking
schreibt kein UPDATE bei Identitaet). Selbe Konvention wie T4
``_mark_room_health_degraded``.

Source of Truth fuer Device-/Zone-Health: dieser Task. Engine-Tasks
duerfen Zonen nach Crash auf ``degraded`` setzen (T4 AE-54), aber nicht
auf ``healthy`` — der Rueckweg laeuft hier.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, cast

import redis
from sqlalchemy import select

from heizung.celery_app import app
from heizung.models import Device, HeatingZone, Room, SensorReading
from heizung.services import redis_client
from heizung.services.health_alerts import emit_health_alert
from heizung.tasks.engine_tasks import _task_session

logger = logging.getLogger(__name__)

# AE-53 Schwellen — Decimal/timedelta, keine Float-Vergleiche.
HEALTHY_MAX_AGE = timedelta(hours=2)
DEGRADED_MAX_AGE = timedelta(hours=24)
OUTLIER_THRESHOLD_C: Decimal = Decimal("7.0")
IMPLAUSIBLE_THRESHOLD = 10
READING_FRESHNESS = timedelta(minutes=30)


@app.task(name="heizung.tasks.health_tasks.compute_health_state")
def compute_health_state() -> dict[str, Any]:
    """Celery-Task-Wrapper. Beat-Schedule 5 min in celery_app.py."""
    return asyncio.run(_compute_health_state_async())


async def _read_implausible_counter(dev_eui: str) -> int:
    """Liest ``implausible:{dev_eui}``-Counter aus Redis via to_thread.

    Defensive: Redis-Offline => 0 zurueckgeben, kein Override. Counter-
    Verlust akzeptiert (S6), nicht-kritischer Audit.
    """

    def _sync_get() -> int:
        client = redis_client.get_redis_client()
        # redis-py-Sync-Client returnt ``bytes | None``. Der Type-Stub von
        # ``Redis.get`` ist via async/sync-Generic-Overload als
        # ``Awaitable[Any] | Any | str`` typisiert — zu breit fuer unseren
        # Sync-Pfad. Explizites Narrowing fuer mypy, kein Runtime-Overhead.
        value = cast(bytes | None, client.get(f"implausible:{dev_eui}"))
        if value is None:
            return 0
        return int(value.decode("utf-8"))

    try:
        return await asyncio.to_thread(_sync_get)
    except redis.RedisError:
        return 0


def _basis_state_from_age(latest_time: datetime | None, now: datetime) -> str:
    """Reines AE-53-Basis-State-Mapping. Kein I/O."""
    if latest_time is None:
        return "silent"
    age = now - latest_time
    if age <= HEALTHY_MAX_AGE:
        return "healthy"
    if age <= DEGRADED_MAX_AGE:
        return "degraded"
    return "silent"


def _outlier_check(
    device_id: int,
    zone_peer_ids: list[int],
    target_state: dict[int, str],
    latest_reading: dict[int, tuple[datetime, Decimal | None]],
    now: datetime,
) -> bool:
    """True, wenn das Device als Outlier gegen den Zone-Median erkennbar ist.

    Nur anwendbar, wenn (a) das Device frisches Reading (<= 30 min) mit
    Temperatur hat, (b) >= 2 weitere healthy-Peers in der Zone ebenfalls
    frische Readings haben, (c) |my_temp - median(peer_temps)| > 7.0.
    """
    my = latest_reading.get(device_id)
    if my is None or my[1] is None or (now - my[0]) > READING_FRESHNESS:
        return False

    peer_temps: list[Decimal] = []
    for peer_id in zone_peer_ids:
        if peer_id == device_id:
            continue
        if target_state.get(peer_id) != "healthy":
            continue
        peer = latest_reading.get(peer_id)
        if peer is None or peer[1] is None:
            continue
        if (now - peer[0]) > READING_FRESHNESS:
            continue
        peer_temps.append(peer[1])

    if len(peer_temps) < 2:
        return False

    zone_median: Decimal = median(peer_temps)
    return abs(my[1] - zone_median) > OUTLIER_THRESHOLD_C


def _derive_zone_state(zone_device_ids: list[int], target_state: dict[int, str]) -> str:
    """Zone-State-Ableitung aus Device-States.

    Brief-Regeln (AE-53):
    - 0 Devices -> ``no_device``
    - Alle ``silent`` -> ``silent``
    - Mind. 1 ``degraded``/``suspicious`` -> ``degraded``
    - Alle ``healthy`` -> ``healthy``

    Strategie-Chat-Erweiterung 2026-05-18 (Brief-Sanktion vor T5-Code):
    - Mischung silent+healthy ohne degraded/suspicious -> ``degraded``
      (partiell offline = nicht voll funktionsfaehig). Im Brief nicht
      explizit aufgefuehrt, aber konsistent mit der ``mind. 1 degraded``-
      Regel: Zone ist nicht voll healthy, also nicht ``healthy``.
    """
    if not zone_device_ids:
        return "no_device"
    states = {target_state.get(d_id) for d_id in zone_device_ids}
    if states == {"silent"}:
        return "silent"
    if "degraded" in states or "suspicious" in states:
        return "degraded"
    if states == {"healthy"}:
        return "healthy"
    return "degraded"


async def _compute_health_state_async() -> dict[str, Any]:
    """Periodische Health-State-Berechnung (AE-53).

    Importierbar als Pure-Function fuer T6 (Mail-Stub konsumiert
    ``silent_transitions``-Liste aus dem Return-Dict).
    """
    silent_transitions: list[dict[str, Any]] = []
    now = datetime.now(tz=UTC)

    async with _task_session() as session:
        devices = list((await session.execute(select(Device))).scalars().all())
        zones = list((await session.execute(select(HeatingZone))).scalars().all())
        rooms = list((await session.execute(select(Room))).scalars().all())

        # Lookup-Maps fuer die Health-Alert-Payload-Anreicherung (T3): Namen
        # via device -> heating_zone -> room. In-Memory, kein extra Roundtrip.
        zone_by_id = {z.id: z for z in zones}
        room_by_id = {r.id: r for r in rooms}

        # Pro Device: juengstes (time, temperature) — eine Query pro
        # Device gegen ix_sensor_reading_device_time, kein N+1-Schmerz
        # bei <500 Devices und 5-min-Kadenz.
        latest_reading: dict[int, tuple[datetime, Decimal | None]] = {}
        for d in devices:
            row = (
                await session.execute(
                    select(SensorReading.time, SensorReading.temperature)
                    .where(SensorReading.device_id == d.id)
                    .order_by(SensorReading.time.desc())
                    .limit(1)
                )
            ).first()
            if row is not None:
                latest_reading[d.id] = (row[0], row[1])

        # Zone-Mapping fuer Peer-Lookup bei Outlier-Check.
        zone_device_ids: dict[int, list[int]] = {}
        for d in devices:
            if d.heating_zone_id is not None:
                zone_device_ids.setdefault(d.heating_zone_id, []).append(d.id)

        # Phase 1: Basis-State pro Device.
        target_state: dict[int, str] = {}
        for d in devices:
            latest = latest_reading.get(d.id)
            target_state[d.id] = _basis_state_from_age(latest[0] if latest else None, now)

        # Phase 2: Outlier-Check — nur Devices, die jetzt healthy sind.
        for d in devices:
            if target_state.get(d.id) != "healthy":
                continue
            if d.heating_zone_id is None:
                continue
            peers = zone_device_ids.get(d.heating_zone_id, [])
            if _outlier_check(d.id, peers, target_state, latest_reading, now):
                target_state[d.id] = "suspicious"

        # Phase 3: Implausible-Counter — nur Devices, die nicht schon silent
        # sind. Counter wird einmal gelesen + gecacht (auch fuer Phase 4
        # Reason-Heuristik).
        counter_cache: dict[str, int] = {}
        for d in devices:
            if target_state.get(d.id) == "silent":
                continue
            counter = await _read_implausible_counter(d.dev_eui)
            counter_cache[d.dev_eui] = counter
            if counter >= IMPLAUSIBLE_THRESHOLD:
                target_state[d.id] = "silent"

        # Phase 4: Apply Device-States + silent_transitions sammeln.
        for d in devices:
            new_state = target_state[d.id]
            previous = d.health_state
            if previous != "silent" and new_state == "silent":
                # Reason-Heuristik: counter_cache wird in Phase 3 nur fuer
                # nicht-silent-Devices befuellt. Wenn ein Device in Phase 1
                # bereits silent ist (offline > 24h, kein Reading), bleibt
                # counter_cache.get(dev_eui, 0) == 0 -> Reason "offline_24h".
                # Wenn Phase 3 die Schwelle 10 erreicht hat (counter >= 10),
                # liegt der Wert im Cache und Reason ist
                # "implausible_readings_24h". Die Verzweigung ist exakt,
                # weil counter_cache nur in Phase 3 geschrieben wird und
                # die Phase-1-silent-Devices garantiert nicht durchlaufen.
                counter = counter_cache.get(d.dev_eui, 0)
                reason = (
                    "implausible_readings_24h"
                    if counter >= IMPLAUSIBLE_THRESHOLD
                    else "offline_24h"
                )
                # T3: Namen via device -> zone -> room aufloesen (innerhalb
                # der Session — Phase 6 emittiert nach Session-Close).
                zone = zone_by_id.get(d.heating_zone_id) if d.heating_zone_id is not None else None
                room = room_by_id.get(zone.room_id) if zone is not None else None
                latest = latest_reading.get(d.id)
                silent_transitions.append(
                    {
                        "device_id": d.id,
                        "dev_eui": d.dev_eui,
                        "reason": reason,
                        "device_name": d.label,
                        "zone_name": zone.name if zone is not None else None,
                        "room_name": room.number if room is not None else None,
                        "triggered_at": now,
                        "last_uplink_at": latest[0] if latest is not None else None,
                        "implausible_count_24h": counter_cache.get(d.dev_eui),
                    }
                )
            if previous != new_state:
                d.health_state = new_state

        # Phase 5: Zone-States ableiten + idempotent schreiben.
        for z in zones:
            dev_ids = zone_device_ids.get(z.id, [])
            new_zone_state = _derive_zone_state(dev_ids, target_state)
            if z.health_state != new_zone_state:
                z.health_state = new_zone_state

        await session.commit()

    # Phase 6: Health-Alerts emittieren fuer alle silent_transitions.
    # T6 (AE-53): Stufe-2 (reason="offline_24h") oder Stufe-3
    # (reason="implausible_readings_24h"). Heute Logger-Stub,
    # SMTP-Versand ist eigener Sprint nach Heizperiode. Reihenfolge
    # NACH commit() ist wichtig: nur persistierter State loest Alarm
    # aus — bei transientem DB-Fehler waere die session bereits in
    # rolled-back-Zustand und kein Phantom-Alarm wuerde rausgehen.
    # silent_transitions-Sammlung in Phase 4 enthaelt bauartbedingt
    # nur previous!=silent->new==silent-Uebergaenge, kein Re-Mail-
    # Sturm beim 5-min-Beat-Tick.
    for transition in silent_transitions:
        level = 3 if transition["reason"] == "implausible_readings_24h" else 2
        emit_health_alert(
            level=level,
            device_id=transition["device_id"],
            dev_eui=transition["dev_eui"],
            reason=transition["reason"],
            device_name=transition["device_name"],
            room_name=transition["room_name"],
            zone_name=transition["zone_name"],
            triggered_at=transition["triggered_at"],
            last_uplink_at=transition["last_uplink_at"],
            implausible_count_24h=transition["implausible_count_24h"],
        )

    return {
        "devices_processed": len(devices),
        "zones_processed": len(zones),
        "silent_transitions": silent_transitions,
    }
