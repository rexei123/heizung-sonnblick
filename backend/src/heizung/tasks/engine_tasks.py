"""Engine-Celery-Tasks.

Sprint 9.1 (Stub) -> Sprint 9.4-5 (echte Engine-Logik):
- ``evaluate_room`` laedt Kontext, faehrt 5-Layer-Pipeline (aktuell nur
  Layer 1 + 5, Walking Skeleton aus Sprint 9.3),
- persistiert ``event_log`` pro Layer (KI-Vorbereitung gemaess AE-08),
- vergleicht mit letztem ``control_command`` ueber Hysterese,
- sendet ggf. Downlink an alle Devices der Heizzonen des Raums,
- schreibt ``control_command`` mit ``sent_to_gateway_at`` (oder NULL bei Fehler).

Async-Aufruf aus Sync-Celery-Task: ``asyncio.run`` umschliesst die Coroutine.
Sprint 9.6 (Live-Test) verifiziert End-to-End mit Vicki-001.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import aiomqtt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import joinedload

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.rules.engine import (
    _last_command_for_room,
    hysteresis_decision,
)
from heizung.rules.engine import (
    evaluate_room as _engine_evaluate_room,
)
from heizung.services import engine_lock
from heizung.services.downlink_adapter import DownlinkError, send_setpoint

# Sprint 9.10 T3.5: Re-Trigger-Verzoegerung wenn der Lock fuer einen Raum
# anderweitig gehalten wird. 5 s ist kurz genug, dass der Burst-Trigger
# (Reading-Eval) nicht gefuehlt verloren geht, lang genug, dass der
# laufende Eval bei normalen Latenzen abgeschlossen ist (Engine-Path
# ~1-2 s lokal, ~3 s Live).
EVAL_LOCK_RETRIGGER_DELAY_S = 5

logger = logging.getLogger(__name__)


# Sprint 9.7a: Pool-Pollution-Fix.
# Jeder Celery-Task spawnt via ``asyncio.run`` einen NEUEN Event-Loop. Eine
# global geteilte ``SessionLocal`` (aus ``heizung.db``) haelt Connections,
# die an einen FRUEHEREN Loop gebunden waren. Folge: asyncpg wirft
# ``cannot perform operation: another operation is in progress``.
#
# Loesung: pro Task-Coroutine eine eigene Engine + Session-Factory bauen
# und am Ende ``engine.dispose()`` rufen. Etwas Overhead pro Task (~10 ms),
# aber keine Race-Conditions mehr.
@contextlib.asynccontextmanager
async def _task_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=False,
        pool_size=2,
        max_overflow=0,
    )
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


@app.task(name="heizung.evaluate_room", bind=True, max_retries=3, default_retry_delay=10)
def evaluate_room(self: Any, room_id: int) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Engine-Eval + Audit + Downlink fuer einen Raum.

    Sprint 9.1 war Stub — ab Sprint 9.4-5 echte Logik. Task-Name
    bleibt `heizung.evaluate_room` (siehe AsyncResult-Lookups).

    Sprint 9.10 T3.5 (AE-40): Pro Raum hoechstens EIN aktiver Eval.
    Lock per Redis-SETNX (Key ``engine:eval:lock:{room_id}``, TTL 30 s).
    Bei Lock-Konflikt wird der Task ueber ``apply_async(countdown=5)``
    erneut in die Queue geschrieben — kein Drop. Der TTL fungiert als
    Watchdog falls ein Worker gekillt wird, bevor ``release`` laeuft.
    """
    if not engine_lock.try_acquire(room_id):
        evaluate_room.apply_async(
            (room_id,),
            countdown=EVAL_LOCK_RETRIGGER_DELAY_S,
        )
        logger.info(
            "evaluate_room: lock busy fuer room_id=%s -> re-trigger in %ss",
            room_id,
            EVAL_LOCK_RETRIGGER_DELAY_S,
        )
        return {
            "room_id": room_id,
            "status": "lock_busy_retriggered",
            "retrigger_in_s": EVAL_LOCK_RETRIGGER_DELAY_S,
        }

    logger.debug("evaluate_room: lock acquired room_id=%s", room_id)
    try:
        return asyncio.run(_evaluate_room_async(room_id))
    finally:
        engine_lock.release(room_id)


@app.task(name="heizung.evaluate_due_rooms", bind=True)
def evaluate_due_rooms(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Sprint 9.7: Beat-getriebene periodische Evaluation.

    Faehrt jede Minute (siehe ``celery_app.beat_schedule``):
    - holt alle Raeume mit ``next_transition_at IS NULL`` ODER ``<= now``
    - schickt fuer jeden ein ``evaluate_room.delay(id)`` (Worker uebernimmt)
    - returnt dict mit ``triggered`` count

    Layer 2 (Sprint 9.8 Vorheizen) wird ``next_transition_at`` selbst setzen.
    Sprint 9.7 setzt nach jeder Eval ``next_transition_at = now + 60s`` als
    Heartbeat — d.h. effektiv evaluiert die Engine derzeit jeden Raum
    mindestens alle 60 s, plus Event-getriggert bei Belegungs-POST.
    """
    return asyncio.run(_evaluate_due_rooms_async())


async def _evaluate_due_rooms_async() -> dict[str, Any]:
    from heizung.models.room import Room

    now = datetime.now(tz=UTC)
    async with _task_session() as session:
        stmt = select(Room.id).where(
            (Room.next_transition_at.is_(None)) | (Room.next_transition_at <= now)
        )
        ids = list((await session.execute(stmt)).scalars().all())

    triggered = 0
    for rid in ids:
        evaluate_room.delay(rid)
        triggered += 1
    logger.info("evaluate_due_rooms: triggered=%s rooms_total=%s", triggered, len(ids))
    return {"triggered": triggered, "now": now.isoformat()}


async def _evaluate_room_async(room_id: int) -> dict[str, Any]:
    eval_id = uuid.uuid4()
    async with _task_session() as session:
        result = await _engine_evaluate_room(session, room_id)
        if result is None:
            logger.warning("evaluate_room: room_id=%s nicht gefunden — skip", room_id)
            return {
                "room_id": room_id,
                "evaluation_id": str(eval_id),
                "status": "skipped_no_room",
            }

        prev = await _last_command_for_room(session, room_id)
        prev_setpoint, prev_at = (None, None) if prev is None else prev
        decision = hysteresis_decision(
            prev_setpoint_c=prev_setpoint,
            prev_issued_at=prev_at,
            new_setpoint_c=result.setpoint_c,
        )

        # Audit-Log: pro Layer eine Row
        for layer in result.layers:
            session.add(
                EventLog(
                    room_id=room_id,
                    evaluation_id=eval_id,
                    layer=layer.layer,
                    setpoint_in=Decimal(prev_setpoint) if prev_setpoint is not None else None,
                    # Sprint 9.10d T2.5: ``layer.setpoint_c`` kann None sein
                    # (aktuell nur Layer 0 inaktiv — Layer hat keinen
                    # Setpoint-Beitrag). EventLog.setpoint_out ist nullable.
                    setpoint_out=(
                        Decimal(layer.setpoint_c) if layer.setpoint_c is not None else None
                    ),
                    reason=layer.reason,
                    details={
                        "detail": layer.detail,
                        "hysteresis_decision": {
                            "should_send": decision.should_send,
                            "reason": decision.reason,
                        },
                        **(layer.extras or {}),
                    },
                )
            )

        sent_devices: list[dict[str, Any]] = []
        if decision.should_send:
            devices = await _get_room_devices(session, room_id)
            if not devices:
                logger.info(
                    "evaluate_room: room_id=%s hat keine aktiven Devices — kein Downlink",
                    room_id,
                )
            for dev in devices:
                cc = ControlCommand(
                    device_id=dev.id,
                    target_setpoint=Decimal(result.setpoint_c),
                    reason=result.base_reason,
                    rule_context=json.dumps(
                        {
                            "evaluation_id": str(eval_id),
                            "layers": [
                                {
                                    "layer": layer.layer.value,
                                    "setpoint_c": layer.setpoint_c,
                                    "reason": layer.reason.value,
                                }
                                for layer in result.layers
                            ],
                        }
                    ),
                )
                session.add(cc)
                try:
                    await send_setpoint(dev.dev_eui, result.setpoint_c)
                    cc.sent_to_gateway_at = datetime.now(tz=UTC)
                    sent_devices.append({"id": dev.id, "dev_eui": dev.dev_eui, "status": "sent"})
                except (aiomqtt.MqttError, DownlinkError) as e:
                    logger.exception(
                        "downlink-fehler dev_eui=%s setpoint=%s err=%s",
                        dev.dev_eui,
                        result.setpoint_c,
                        e,
                    )
                    sent_devices.append({"id": dev.id, "dev_eui": dev.dev_eui, "status": "failed"})

        # Sprint 9.7: Heartbeat. Layer 2 (9.8) ueberschreibt next_transition_at
        # mit echten Schaltpunkten (Vorheiz-Beginn, Nachtabsenkung-Wechsel).
        from datetime import timedelta as _td

        from heizung.models.room import Room as _Room

        now = datetime.now(tz=UTC)
        await session.execute(
            select(_Room).where(_Room.id == room_id)
        )  # warm-up der relation map; ergebnis irrelevant
        room_obj = await session.get(_Room, room_id)
        if room_obj is not None:
            room_obj.last_evaluated_at = now
            room_obj.next_transition_at = now + _td(seconds=60)
        await session.commit()

        return {
            "room_id": room_id,
            "evaluation_id": str(eval_id),
            "setpoint_c": result.setpoint_c,
            "should_send": decision.should_send,
            "hysteresis": decision.reason,
            "devices": sent_devices,
        }


async def _get_room_devices(session: Any, room_id: int) -> list[Device]:
    """Alle aktiven Devices, die Heizzonen dieses Raums zugeordnet sind."""
    stmt = (
        select(Device)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .where(Device.is_active.is_(True))
        .options(joinedload(Device.heating_zone))
    )
    return list((await session.execute(stmt)).unique().scalars().all())
