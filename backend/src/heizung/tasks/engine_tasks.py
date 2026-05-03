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
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import aiomqtt
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from heizung.celery_app import app
from heizung.db import SessionLocal
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
from heizung.services.downlink_adapter import DownlinkError, send_setpoint

logger = logging.getLogger(__name__)


@app.task(name="heizung.evaluate_room", bind=True, max_retries=3, default_retry_delay=10)
def evaluate_room(self: Any, room_id: int) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Engine-Eval + Audit + Downlink fuer einen Raum.

    Sprint 9.1 war Stub — ab Sprint 9.4-5 echte Logik. Task-Name
    bleibt `heizung.evaluate_room` (siehe AsyncResult-Lookups).
    """
    return asyncio.run(_evaluate_room_async(room_id))


async def _evaluate_room_async(room_id: int) -> dict[str, Any]:
    eval_id = uuid.uuid4()
    async with SessionLocal() as session:
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
                    setpoint_out=Decimal(layer.setpoint_c),
                    reason=layer.reason,
                    details={
                        "detail": layer.detail,
                        "hysteresis_decision": {
                            "should_send": decision.should_send,
                            "reason": decision.reason,
                        },
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
