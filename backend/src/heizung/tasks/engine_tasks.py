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
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, EventLogLayer
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import (
    HysteresisDecision,
    _last_command_for_device,
    _last_command_for_room,
    hysteresis_decision,
)
from heizung.rules.engine import (
    evaluate_room as _engine_evaluate_room,
)
from heizung.services import (
    alert_throttle,
    engine_abgleich,
    engine_lock,
    override_service,
    resync_flag,
)
from heizung.services.business_audit_service import record_business_action
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
    _ping_engine_healthcheck()
    return {"triggered": triggered, "now": now.isoformat()}


# Der Beat feuert jede Minute. Der Monitor ist auf 5 Minuten Periode
# eingestellt, ein Ping je Minute waere also 5x mehr als noetig. 290 s
# statt 300 s als Sperrzeit: bei exakt 300 s koennte ein Tick knapp vor
# Ablauf landen und der naechste erst 60 s spaeter, was den Abstand auf
# 6 Minuten dehnt und den Monitor grundlos ausloest.
ENGINE_PING_THROTTLE_S = 290
ENGINE_PING_KEY = "engine_tick"
ENGINE_PING_TIMEOUT_S = 5


def _ping_engine_healthcheck() -> None:
    """Dead-Man-Ping fuer den Engine-Takt (Sprint 18, CLAUDE.md 5.76).

    **Was der Ping belegt und was nicht.** Er belegt, dass Beat und Worker
    die Kette durchlaufen: der Beat hat getaktet, der Task lief bis zum
    Ende, die Datenbank war erreichbar. Er belegt **nicht**, dass die
    Auswertung je Zimmer korrekt war. Nach AE-54 ist jede Raum-Evaluation
    einzeln gekapselt — ein Lauf, in dem *jede* Zimmer-Evaluation
    scheitert, kommt trotzdem hier an und pingt gruen. Wer das abdecken
    will, braucht einen Alarm auf die Fehlerquote, nicht auf den Takt.

    Faellt Redis aus, greift die Drosselung nicht und es wird bei jedem
    Tick gepingt. Harmlos: der Monitor zaehlt nur, ob ueberhaupt etwas
    ankommt. Ein Sonderfall dafuer waere mehr Code als Nutzen.
    """
    url = get_settings().healthcheck_engine_url
    if not url:
        return
    if not alert_throttle.should_send(ENGINE_PING_KEY, "beat", ttl_s=ENGINE_PING_THROTTLE_S):
        return
    try:
        with httpx.Client(timeout=ENGINE_PING_TIMEOUT_S) as client:
            client.get(url).raise_for_status()
    except Exception:  # noqa: BLE001 - ein Ping darf den Tick nie kippen
        logger.warning("engine_healthcheck_ping_fehlgeschlagen", exc_info=True)


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


# Sprint 20f (T3): Audit-Aktion, wenn der Abgleich aufgibt. Eigener Name, kein
# Anhaengen an ``DEVICE_INBOUND_TEST`` oder den Engine-Trace: das hier ist
# kein Pruefergebnis und keine Steuerentscheidung, sondern die Meldung, dass
# eine Nachbesserung **nicht** gewirkt hat.
AUDIT_ABGLEICH_ERSCHOEPFT = "ENGINE_ABGLEICH_ERSCHOEPFT"


async def _melde_abgleich_erschoepft(
    session: AsyncSession,
    *,
    dev: Device,
    zone_id: int,
    room_id: int,
    ist_wert: int,
    soll_wert: int,
    versuche: int,
) -> None:
    """Schreibt **einmal** einen Audit-Eintrag, wenn der Abgleich aufgibt.

    Sprint 20f (T3). Nach ``MAX_VERSUCHE`` erfolglosen Nachsendungen wird
    nicht weiter gesendet — ein Geraet an der Funkgrenze wuerde sonst bei
    jedem Tick angefunkt, und jeder Downlink ist eine Motorbewegung (§0 S4).

    **Das Aufgeben darf nicht stillschweigend passieren.** Ein Geraet, das
    dauerhaft einen anderen Wert haelt als die Engine will, heizt ein Zimmer
    falsch — und niemand sieht es, weil die Oberflaeche den Engine-Soll
    anzeigt und nicht den Geraete-Wert. Genau diese Sorte stiller Ausfall ist
    §5.76: wer nur die Mechanik ueberwacht ("wurde gesendet"), findet ihn
    nicht.

    **Einmal, nicht bei jedem Tick.** Die Drosselung haengt am Zaehler-Stand:
    ``alert_throttle`` sperrt je ``dev_eui`` fuer 24 h. Sonst entstuende bei
    einem Geraet an der Funkgrenze im Minutentakt ein Audit-Eintrag, und der
    Melder waere nach einem Tag einer, dem niemand mehr zusieht (§5.79).

    Kein Mail-Versand: der Brief zu 20f sieht fuer T3 eine Warnung und einen
    Audit-Eintrag vor, keine Benachrichtigung. Die Mail-Entscheidung gehoert
    zum Hinweis-Pfad aus 20e und wird dort gemeinsam getroffen.
    """
    if not await asyncio.to_thread(
        alert_throttle.should_send,
        "engine_abgleich_erschoepft",
        dev.dev_eui,
        ttl_s=86400,
    ):
        return

    logger.warning(
        "engine_abgleich erschoepft dev_eui=%s device_id=%s zone_id=%s "
        "ist=%s soll=%s versuche=%s — es wird nicht weiter gesendet",
        dev.dev_eui,
        dev.id,
        zone_id,
        ist_wert,
        soll_wert,
        versuche,
    )
    await record_business_action(
        session,
        user_id=None,
        action=AUDIT_ABGLEICH_ERSCHOEPFT,
        target_type="device",
        target_id=dev.id,
        old_value=None,
        new_value={
            "dev_eui": dev.dev_eui,
            "hardware_nummer": dev.label,
            "room_id": room_id,
            "zone_id": zone_id,
            "gemeldeter_sollwert": ist_wert,
            "engine_sollwert": soll_wert,
            "versuche": versuche,
            "hinweis": (
                "Das Geraet uebernimmt den Engine-Sollwert nicht. Funk, "
                "Batterie oder Hardware pruefen; nach der Behebung regelt "
                "der Abgleich von selbst nach."
            ),
        },
        request_ip=None,
    )


async def _gemeldete_sollwerte(session: AsyncSession, device_ids: Sequence[int]) -> dict[int, int]:
    """Letzter vom Geraet **gemeldeter** Sollwert je Geraet (Sprint 20f, T3).

    ``DISTINCT ON (device_id)`` ueber ``ix_sensor_reading_device_time`` — ein
    Roundtrip fuer alle Geraete einer Zone, nicht einer je Geraet.

    Das ist die Groesse, die der Engine bis Sprint 20f gefehlt hat. Sie kannte
    ``control_command.target_setpoint`` (was sie **wollte**) und hat die
    Hysterese darauf gerechnet; was am Geraet **steht**, stand nie in der
    Rechnung. Geraete 048 und 057 blieben deshalb nach einer Montage-Drehung
    auf 20 °C, waehrend der Engine-Soll 18 °C war.

    Zeilen ohne ``setpoint`` werden weggelassen: eine Zeile, die den Wert
    nicht fuehrt, ist kein Beleg fuer eine Abweichung. Dieselbe
    Drei-Zustands-Regel wie ueberall sonst — NULL ist keine Aussage.
    """
    if not device_ids:
        return {}
    stmt = (
        select(SensorReading.device_id, SensorReading.setpoint)
        .where(SensorReading.device_id.in_(list(device_ids)))
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    rows = (await session.execute(stmt)).all()
    return {int(did): int(sp) for did, sp in rows if sp is not None}


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

        # Sprint 20f (T3): was melden die Geraete dieser Zone, und gibt es
        # einen Override? Beides einmal je Zone, nicht je Geraet.
        gemeldet = await _gemeldete_sollwerte(session, [d.id for d in devices])
        aktiver_override = await override_service.get_active(
            session, room_id, heating_zone_id=zone.id
        )

        # Per-Vicki-Hysterese-Check
        send_payloads: list[tuple[Device, ControlCommand, str]] = []
        # Sprint 20f (T3): welche Geraete senden wegen des Abgleichs? Nur fuer
        # die wird nach dem Downlink ein Versuch gezaehlt.
        abgleich_ids: set[int] = set()
        skipped_count = 0
        for dev in devices:
            prev = await _last_command_for_device(session, dev.id)
            prev_sp, prev_at = (None, None) if prev is None else prev
            dev_decision = hysteresis_decision(
                prev_setpoint_c=prev_sp,
                prev_issued_at=prev_at,
                new_setpoint_c=zone_target_setpoint_c,
            )

            # Sprint 15c (AE-63): Reboot-Re-Sync-Bypass. ``resync_flag.consume``
            # ist atomarer GETDEL — gibt True zurueck wenn das Flag gesetzt
            # war (und ist jetzt geloescht). Konsumiert unabhaengig von
            # ``dev_decision.should_send`` (cleanup, vermeidet doppelten
            # Re-Sync im naechsten Tick wenn die Hysterese ohnehin senden
            # wuerde). Nur wenn die Hysterese skippen wollte UND das Flag
            # gesetzt war, ueberschreiben wir die Entscheidung auf
            # forced-send mit ``reason=reboot_resync``.
            flag_was_set = await asyncio.to_thread(resync_flag.consume, dev.dev_eui)
            resync_forced = False
            if flag_was_set and not dev_decision.should_send:
                resync_forced = True
                dev_decision = HysteresisDecision(
                    should_send=True,
                    reason=f"reboot_resync (was: {dev_decision.reason})",
                )
                logger.info(
                    "reboot_resync forced dev_eui=%s zone_id=%s setpoint_c=%s",
                    dev.dev_eui,
                    zone.id,
                    zone_target_setpoint_c,
                )

            # Sprint 20f (T3): Engine-Abgleich. Die Hysterese hat eben
            # entschieden, ob sich der **eigene Wille** geaendert hat. Sie
            # weiss nichts darueber, was am Geraet steht — und genau dort lag
            # der Befund: Geraete 048 und 057 blieben nach einer
            # Montage-Drehung auf 20 °C, waehrend der Engine-Soll 18 °C war
            # und kein Override existierte. Die Hysterese sah ``delta = 0``
            # und schwieg.
            #
            # Drei Bedingungen muessen zusammenkommen:
            #   1. die Hysterese wollte nicht senden,
            #   2. das Geraet meldet einen **anderen** Wert als den Soll,
            #   3. es gibt **keinen** aktiven Override fuer diese Zone.
            #
            # Die dritte ist die wichtigste. Ein Gast-Override ist genau der
            # Fall, in dem das Geraet absichtlich abweicht — ein Abgleich
            # wuerde den Gastwunsch ueberschreiben, und zwar jede halbe
            # Stunde. Deshalb steht hier nicht "ausser bei Override" als
            # Nebenbedingung, sondern als Hauptbedingung.
            ist_wert = gemeldet.get(dev.id)
            abgleich_forced = False
            if (
                not dev_decision.should_send
                and not resync_forced
                and aktiver_override is None
                and ist_wert is not None
                and ist_wert != zone_target_setpoint_c
            ):
                # Drosselung und Zaehler: hoechstens 1x/30 min je Geraet, nach
                # drei erfolglosen Versuchen Schluss. Jeder Downlink ist eine
                # Motorbewegung (§0 S4) — ein Geraet an der Funkgrenze wuerde
                # ohne Grenze bei jedem Tick angefunkt.
                if await asyncio.to_thread(engine_abgleich.darf_senden, dev.dev_eui):
                    abgleich_forced = True
                    dev_decision = HysteresisDecision(
                        should_send=True,
                        reason=(
                            f"engine_abgleich: Geraet meldet {ist_wert}, "
                            f"Soll {zone_target_setpoint_c} (was: {dev_decision.reason})"
                        ),
                    )
                    logger.info(
                        "engine_abgleich forced dev_eui=%s zone_id=%s ist=%s soll=%s",
                        dev.dev_eui,
                        zone.id,
                        ist_wert,
                        zone_target_setpoint_c,
                    )
                else:
                    # Entweder die Sperre steht noch, oder die drei Versuche
                    # sind verbraucht. Der zweite Fall ist ein Befund und
                    # gehoert ins Audit — einmal, nicht bei jedem Tick: die
                    # Drosselung des Alarms haengt am selben Zaehler-Stand.
                    stand = await asyncio.to_thread(engine_abgleich.versuche, dev.dev_eui)
                    if stand >= engine_abgleich.MAX_VERSUCHE:
                        await _melde_abgleich_erschoepft(
                            session,
                            dev=dev,
                            zone_id=zone.id,
                            room_id=room_id,
                            ist_wert=ist_wert,
                            soll_wert=zone_target_setpoint_c,
                            versuche=stand,
                        )
            elif ist_wert is not None and ist_wert == zone_target_setpoint_c:
                # Geraet steht auf dem Soll — Zaehler zuruecksetzen, damit ein
                # spaeterer Fall wieder drei Versuche hat.
                await asyncio.to_thread(engine_abgleich.erfolg_gemeldet, dev.dev_eui)

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
            cc_reason = CommandReason.REBOOT_RESYNC if resync_forced else base_reason
            cc = ControlCommand(
                device_id=dev.id,
                target_setpoint=Decimal(zone_target_setpoint_c),
                reason=cc_reason,
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
            if abgleich_forced:
                abgleich_ids.add(dev.id)

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
                # Sprint 20f (T3): Abgleich-Versuch zaehlen. Bewusst **nach**
                # dem Senden und bewusst **nicht** an den Erfolg des Downlinks
                # gebunden: geloescht wird der Zaehler erst, wenn das Geraet
                # den Wert meldet. Ein Downlink, der im Gateway verschwindet,
                # zaehlt damit mit — und das ist richtig, denn er hat nichts
                # bewirkt (§5.76: die Wirkung zaehlt, nicht die Mechanik).
                if dev.id in abgleich_ids:
                    await asyncio.to_thread(engine_abgleich.versuch_gezaehlt, dev.dev_eui)
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
