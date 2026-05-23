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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, EventLogLayer
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.rules.engine import (
    _last_command_for_device,
    _last_command_for_room,
    hysteresis_decision,
)
from heizung.rules.engine import (
    evaluate_room as _engine_evaluate_room,
)
from heizung.services import engine_lock
from heizung.services.device_service import get_active_devices_for_zone
from heizung.services.downlink_adapter import send_setpoint

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
    # Sprint 11 T4 (AE-54): Top-Level-Sicherheitsgurt. Ein beliebiger
    # Crash innerhalb der Eval (Layer-Funktion, DB-Connection-Loss
    # ausserhalb des Pool-Pre-Pings, unerwartete Exception aus einer
    # Library) wird hier gefangen, geloggt, und alle HeatingZones des
    # Raums werden auf health_state='degraded' gesetzt. Kein Re-Raise:
    # `evaluate_room.max_retries=3` greift nur fuer transiente Fehler,
    # die in tieferen try/except nicht abgefangen werden — ein finaler
    # Crash hier wuerde sonst den Worker bei 100 Vickis x 60-s-Beat
    # mit Retry-Backlog laehmen. Source of Truth fuer den Uebergang
    # zurueck nach 'healthy' bleibt der Compute-Task aus T5.
    # ``Exception`` (nicht ``BaseException``): KeyboardInterrupt,
    # SystemExit, asyncio.CancelledError muessen durchkommen.
    try:
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

            # Sprint 12 T2: nur ``prev_setpoint`` aus ``_last_command_for_room``
            # uebrig, ausschliesslich als Audit-Info in
            # ``EventLog.setpoint_in`` jeder Layer-Row. Per-Vicki-Hysterese
            # uebernimmt ``_dispatch_downlinks_per_zone`` mit
            # ``_last_command_for_device``. Room-Level-``decision`` und ihre
            # Return-Dict-Keys ``should_send``/``hysteresis`` wurden
            # entfernt — verhaltensirrelevant + §5.20-Drift-Muster
            # (irrefuehrende Info im Audit-Pfad).
            prev = await _last_command_for_room(session, room_id)
            prev_setpoint = None if prev is None else prev[0]

            # Sprint 12 T2: Multi-Vicki Schreib-Pfad (STRATEGIE §4.2,
            # AE-51 P3 + D5). Per-Zone-Iteration, healthy-Filter,
            # per-Vicki-Hysterese, parallele Submission via asyncio.gather,
            # individuelles try/except. Kein Rollback bei Teil-Erfolg
            # (Annahme A2 aus Sprint-12-Brief).
            # Sprint 12a T5 (AE-58 Option G): ``zone_overrides`` aus
            # ``result`` durchreichen — pro Zone bekommt der Dispatch
            # entweder den Zone-spezifischen Setpoint oder den Room-Default
            # (``setpoint_c``) als Fallback.
            per_device_results, per_zone_status = await _dispatch_downlinks_per_zone(
                session=session,
                room_id=room_id,
                target_setpoint_c=result.setpoint_c,
                base_reason=result.base_reason,
                eval_id=eval_id,
                zone_overrides=result.zone_overrides,
            )
            sent_devices = per_device_results

            # Audit-Log: pro Layer eine Row. HARD_CLAMP-Row bekommt
            # zusaetzlich die per-Vicki-Sub-Traces in JSONB — EventLog-PK
            # (time, room_id, evaluation_id, layer) erlaubt KEINE eigenen
            # Rows pro Vicki ohne PK-Migration (Drift D7); Aggregat in
            # details statt PK-Erweiterung.
            for layer in result.layers:
                base_details: dict[str, Any] = {
                    "detail": layer.detail,
                    **(layer.extras or {}),
                }
                if layer.layer == EventLogLayer.HARD_CLAMP:
                    base_details["downlink_per_device"] = per_device_results
                    base_details["downlink_zone_status"] = per_zone_status
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
                        details=base_details,
                    )
                )

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

            # Sprint 9.11y: Passiver Inferred-Window-Detector (AE-47).
            # Laeuft NACH der regulaeren Engine-Pipeline + ControlCommand-
            # Insert: keine Setpoint-Aenderung, nur event_log-Eintrag bei
            # Treffer. Atomar in derselben Session/Transaction.
            try:
                from heizung.rules.inferred_window import detect_inferred_window
                from heizung.services.event_log import log_inferred_window_event

                inferred = await detect_inferred_window(session, room_id, now)
                if inferred is not None:
                    await log_inferred_window_event(session, inferred)
                    logger.info(
                        "event_type=INFERRED_WINDOW_OBSERVATION room_id=%s "
                        "delta_c=%s devices=%s setpoint_c=%s",
                        inferred.room_id,
                        inferred.delta_c,
                        inferred.devices_observed,
                        inferred.setpoint_c,
                    )
            except Exception:
                # Inferred-Detection ist nicht engine-kritisch — failure
                # darf den regulaeren Eval-Commit nicht blockieren.
                logger.exception("inferred_window detector fehlgeschlagen room_id=%s", room_id)

            await session.commit()

            return {
                "room_id": room_id,
                "evaluation_id": str(eval_id),
                "setpoint_c": result.setpoint_c,
                "devices": sent_devices,
            }
    except Exception:
        logger.exception("room_eval_failed", extra={"room_id": room_id})
        await _mark_room_health_degraded(room_id)
        return {"room_id": room_id, "status": "failed_marked_degraded"}


async def _mark_room_health_degraded(room_id: int) -> None:
    """Setzt ``heating_zone.health_state='degraded'`` fuer alle Zonen des Raums.

    Aufruf nur im except-Pfad von ``_evaluate_room_async`` (Sprint 11 T4,
    AE-54). Erfolgreicher Eval-Pfad aendert ``health_state`` NICHT — Source
    of Truth fuer den Uebergang zurueck nach ``healthy`` ist der
    Compute-Task aus T5.

    Idempotent: ist die Zone bereits ``degraded``, wird kein Attribut
    geschrieben (vermeidet UPDATE-Spam bei Dauer-Crashes und nutzt das
    SQLAlchemy-Attribut-Tracking aus — Wert-Identitaet ohne Setter-Aufruf
    triggert kein ``before_update``).

    Bei nicht-existentem ``room_id``: zones-Liste ist leer, for-Schleife
    noop, ``commit`` ist no-op. Bewusste Eigenschaft (kein FK-/Existence-
    Check) — der Aufrufer ist der except-Pfad einer bereits gescheiterten
    Eval und soll nicht selbst nochmal kippen koennen.

    Eigene Session-Boundary via ``_task_session()``: separat von der
    Eval-Session, die im Exception-Zustand sein kann (rolled-back oder
    transient-broken).
    """
    async with _task_session() as session:
        zones = (
            (await session.execute(select(HeatingZone).where(HeatingZone.room_id == room_id)))
            .scalars()
            .all()
        )
        for zone in zones:
            if zone.health_state != "degraded":
                zone.health_state = "degraded"
        await session.commit()


async def _get_zones_for_room(session: AsyncSession, room_id: int) -> list[HeatingZone]:
    """Alle HeatingZones eines Raums (Sprint 12 T2).

    Pro-Zone-Iteration im Schreib-Pfad. Reihenfolge ueber ``id ASC`` fuer
    deterministisches Verhalten in Tests + Trace.
    """
    stmt = select(HeatingZone).where(HeatingZone.room_id == room_id).order_by(HeatingZone.id)
    return list((await session.execute(stmt)).scalars().all())


async def _get_zone_devices(session: AsyncSession, zone_id: int) -> list[Device]:
    """Aktive + healthy Devices einer Zone (Sprint 12 T2, AE-51 P3 + D3).

    Sprint 13b.1 (AE-57): Lifecycle-Filter via ``get_active_devices_for_zone``
    (``retired_at IS NULL``). ``health_state='healthy'``-Filter bleibt
    in dieser Funktion, weil Engine-spezifisch — Devices in Status
    ``silent``, ``degraded`` oder ``suspicious`` (AE-53) werden NICHT
    angesteuert (kein Downlink-Versuch, keine ControlCommand-Row).

    Reihenfolge ``id ASC`` (Helper-Default) fuer deterministisches
    Verhalten in Tests + Trace.
    """
    active_devices = await get_active_devices_for_zone(session, zone_id)
    return [d for d in active_devices if d.health_state == "healthy"]


async def _dispatch_downlinks_per_zone(
    *,
    session: AsyncSession,
    room_id: int,
    target_setpoint_c: int,
    base_reason: CommandReason,
    eval_id: uuid.UUID,
    zone_overrides: dict[int, int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sprint 12 T2 — Multi-Vicki Schreib-Pfad (STRATEGIE §4.2, AE-51 P3).

    Iteriert pro Zone des Raums, fuehrt per-Vicki-Hysterese aus, schickt
    die Setpoint-Downlinks paralle ueber ``asyncio.gather`` mit
    ``return_exceptions=True``. Pro Erfolg/Fehler ein ``ControlCommand``-
    Eintrag (Erfolg setzt ``sent_to_gateway_at``, Fehler laesst es NULL).

    Hysterese-Bypass: hysterese-skipped Vickis bekommen KEINEN
    ControlCommand-Eintrag (nur Trace via per_device_results), weil kein
    Downlink-Versuch stattfindet.

    Returns:
        ``(per_device_results, per_zone_status)``

        - ``per_device_results``: pro versuchten Vicki ein Dict mit
          ``zone_id``, ``device_id``, ``dev_eui``, ``status``
          (``sent`` | ``failed`` | ``skipped_hysteresis``),
          ``hysteresis_reason``, ``error`` (str | None).
        - ``per_zone_status``: pro Zone des Raums ein Dict mit
          ``zone_id``, ``count_sent``, ``count_failed``, ``count_skipped``,
          ``all_failed`` (bool, true wenn count_sent==0 UND count_failed>0).

    ``target_setpoint_c`` ist bereits int aus ``engine.py``'s _quantize —
    ganzzahlig vor Hysterese-Check (RUNBOOK §10d.7 / Vicki-Hardware-Constraint).

    Sprint 12a T5 (AE-58 Option G): ``zone_overrides`` ist ein optionaler
    Dict ``zone_id -> int_setpoint``. Pro Zone wird ``zone_overrides[zone_id]``
    bevorzugt, sonst Fallback auf ``target_setpoint_c`` (Room-Default).
    """
    zone_overrides = zone_overrides or {}
    zones = await _get_zones_for_room(session, room_id)
    per_device_results: list[dict[str, Any]] = []
    per_zone_status: list[dict[str, Any]] = []

    for zone in zones:
        # Sprint 12a T5: pro Zone den Zone-spezifischen Setpoint, sonst
        # Room-Default.
        zone_target_setpoint_c = zone_overrides.get(zone.id, target_setpoint_c)
        devices = await _get_zone_devices(session, zone.id)
        if not devices:
            per_zone_status.append(
                {
                    "zone_id": zone.id,
                    "count_sent": 0,
                    "count_failed": 0,
                    "count_skipped": 0,
                    "all_failed": False,
                    "detail": "no_healthy_active_devices",
                }
            )
            continue

        # Per-Vicki-Hysterese-Check
        send_payloads: list[tuple[Device, ControlCommand, str]] = []
        skipped_count = 0
        for dev in devices:
            prev = await _last_command_for_device(session, dev.id)
            prev_sp, prev_at = (None, None) if prev is None else prev
            dev_decision = hysteresis_decision(
                prev_setpoint_c=prev_sp,
                prev_issued_at=prev_at,
                new_setpoint_c=zone_target_setpoint_c,
            )
            if not dev_decision.should_send:
                skipped_count += 1
                per_device_results.append(
                    {
                        "zone_id": zone.id,
                        "device_id": dev.id,
                        "dev_eui": dev.dev_eui,
                        "status": "skipped_hysteresis",
                        "hysteresis_reason": dev_decision.reason,
                        "error": None,
                    }
                )
                continue
            cc = ControlCommand(
                device_id=dev.id,
                target_setpoint=Decimal(zone_target_setpoint_c),
                reason=base_reason,
                rule_context=json.dumps(
                    {
                        "evaluation_id": str(eval_id),
                        "zone_id": zone.id,
                        "hysteresis_reason": dev_decision.reason,
                    }
                ),
            )
            session.add(cc)
            send_payloads.append((dev, cc, dev_decision.reason))

        if not send_payloads:
            per_zone_status.append(
                {
                    "zone_id": zone.id,
                    "count_sent": 0,
                    "count_failed": 0,
                    "count_skipped": skipped_count,
                    "all_failed": False,
                    "detail": "all_hysteresis_skipped",
                }
            )
            continue

        # Parallele Downlink-Submission via asyncio.gather. ``return_exceptions=
        # True`` macht aus jeder Exception einen Wert in ``outcomes`` — KEINE
        # asyncio.gather()-Cascade-Cancellation, kein Rollback (A2).
        coros = [send_setpoint(dev.dev_eui, zone_target_setpoint_c) for dev, _, _ in send_payloads]
        outcomes = await asyncio.gather(*coros, return_exceptions=True)

        count_sent = 0
        count_failed = 0
        now_sent = datetime.now(tz=UTC)
        for (dev, cc, hyst_reason), outcome in zip(send_payloads, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                count_failed += 1
                logger.exception(
                    "downlink_failed dev_eui=%s device_id=%s zone_id=%s setpoint_c=%s",
                    dev.dev_eui,
                    dev.id,
                    zone.id,
                    zone_target_setpoint_c,
                    exc_info=outcome,
                )
                per_device_results.append(
                    {
                        "zone_id": zone.id,
                        "device_id": dev.id,
                        "dev_eui": dev.dev_eui,
                        "status": "failed",
                        "hysteresis_reason": hyst_reason,
                        "error": f"{type(outcome).__name__}: {outcome}",
                    }
                )
            else:
                count_sent += 1
                cc.sent_to_gateway_at = now_sent
                per_device_results.append(
                    {
                        "zone_id": zone.id,
                        "device_id": dev.id,
                        "dev_eui": dev.dev_eui,
                        "status": "sent",
                        "hysteresis_reason": hyst_reason,
                        "error": None,
                    }
                )

        all_failed = count_sent == 0 and count_failed > 0
        per_zone_status.append(
            {
                "zone_id": zone.id,
                "count_sent": count_sent,
                "count_failed": count_failed,
                "count_skipped": skipped_count,
                "all_failed": all_failed,
            }
        )
        if all_failed:
            logger.warning(
                "downlink_failed_all_zone zone_id=%s room_id=%s setpoint_c=%s",
                zone.id,
                room_id,
                target_setpoint_c,
            )

    return per_device_results, per_zone_status
