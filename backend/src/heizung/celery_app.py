"""Celery-Application fuer die Regel-Engine.

Sprint 9.1 (2026-05-03):
Setup ohne tasks. Die Engine-Tasks (evaluate_room, evaluate_due_rooms)
werden in spaeteren Sub-Sprints in ``heizung.tasks.engine_tasks``
implementiert. Hier nur der App-Singleton + Konfiguration.

Worker-Aufruf (Container-Service ``celery_worker``):
    celery -A heizung.celery_app worker --concurrency=2 --loglevel=info -Q heizung_default

Beat-Scheduler (kommt in Sprint 9.7 als eigener Container):
    celery -A heizung.celery_app beat --loglevel=info

Test-Hinweis:
    Mit ``app.conf.task_always_eager = True`` laufen Tasks synchron
    im aufrufenden Thread — keine Worker-Container fuer Pytest noetig.
"""

from __future__ import annotations

import asyncio
import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from heizung.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

# Celery-App-Singleton. ``include`` zeigt auf alle Module, in denen
# ``@app.task``-Dekoratoren leben — bisher nur engine_tasks (Stub).
app: Celery = Celery(
    "heizung",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "heizung.tasks.engine_tasks",
        "heizung.tasks.health_tasks",
        "heizung.tasks.override_cleanup_tasks",
        "heizung.tasks.occupancy_import_tasks",
        "heizung.tasks.occupancy_status_tasks",
        "heizung.tasks.pin_reminder_tasks",
    ],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # task_acks_late=True: Worker confirmt erst NACH Task-Run, damit
    # crashed Worker den Job nochmal bekommen. Wichtig fuer Engine —
    # eine Engine-Eval ist idempotent (Audit-Log gibt 1 Row, nicht doppelt).
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Concurrency=2 wie im Brief vereinbart (CPX22-RAM-konservativ).
    worker_concurrency=2,
    task_default_queue="heizung_default",
    # Sprint 9.10 T3.5 / AE-40: Engine-Task-Lock ist im Task selbst
    # implementiert (services.engine_lock, Redis-SETNX, TTL 30 s) — siehe
    # tasks.engine_tasks.evaluate_room. Die Limits hier sind generelle
    # Tasks-Watchdogs; der TTL des Lock muss >= task_time_limit sein, damit
    # ein gekillter Task seinen Lock nicht ueber das Limit hinaus haelt.
    task_soft_time_limit=20,
    task_time_limit=30,
    # Sprint 9.7: Beat-Schedule fuer autonome periodische Evaluation.
    # ``celery_beat``-Container ruft alle 60 s ``evaluate_due_rooms`` auf.
    beat_schedule={
        "evaluate-due-rooms-every-60s": {
            "task": "heizung.evaluate_due_rooms",
            "schedule": 60.0,
            "options": {"queue": "heizung_default"},
        },
        # Sprint 9.9 T7: Daily-Cleanup fuer abgelaufene Manual-Overrides.
        # 03:00 UTC = niedriger Traffic, vor erster Engine-Tick-Welle des Tages.
        "cleanup-expired-overrides-daily": {
            "task": "heizung.cleanup_expired_overrides",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "heizung_default"},
        },
        # Sprint 11 T5 (AE-53): Health-State-Compute alle 5 min.
        # Liest sensor_reading.MAX(time) pro Device + Redis-Implausible-
        # Counter, leitet device.health_state + heating_zone.health_state
        # ab. Returns silent_transitions-Liste (T6-Mail-Stub-Input).
        "compute-health-state-every-5min": {
            "task": "heizung.tasks.health_tasks.compute_health_state",
            "schedule": 300.0,
            "options": {"queue": "heizung_default"},
        },
        # Sprint 15e (AE-66): Belegungs-Import-Staleness-Watchdog.
        # Stuendlich zur Minute 20, NICHT einmal taeglich zu einem festen
        # UTC-Slot. Bis zum 26.09.2026 stand hier crontab(hour=8, minute=15)
        # mit dem Kommentar "08:15 UTC liegt ganzjaehrig NACH 09:00
        # Europe/Vienna" — und dem Zusatz, man muesse den Slot nachziehen,
        # wenn die Schwelle spaeter gestellt wird.
        #
        # Genau das ist die Kopplung, die man nicht haben will: die Schwelle
        # ist seit Migration 0022 in der Oberflaeche editierbar, der Beat-Slot
        # nicht. Wer sie auf 14:00 stellt, haette einen Waechter, der um
        # 10:15 Ortszeit prueft und nie etwas melden kann — lautlos.
        #
        # Stuendlich entkoppelt beides. Der Task no-opt vor der Schwelle, und
        # nach dem ersten STALE-Audit greift der Tages-Guard
        # (_stale_exists_for_list_date) — es gibt also hoechstens eine Mail
        # je Tag, egal wie oft geprueft wird. Preis: 24 statt 1 Lauf pro Tag,
        # jeder ein paar Queries.
        "occupancy-import-freshness-hourly": {
            "task": "heizung.check_occupancy_import_freshness",
            "schedule": crontab(minute=20),
            "options": {"queue": "heizung_default"},
        },
        # Sprint 15g (AE-68): Periodischer room.status-Sync. Trifft die
        # uhrzeitgenauen Check-in-14:00- / Check-out-11:00-Uebergaenge ohne
        # Import-Event (Zeiten stecken als UTC-Timestamp in check_in/
        # check_out, Import-Defaults via GlobalConfig). 60 s = Drift-Fenster
        # <= 60 s, fuer Check-in/out unkritisch (Vorheizen ueber Layer 2 vor
        # check_in). Eigener Task statt Engine-Tick-Anhang — Belegungs-
        # Domain bleibt aus der Engine.
        "sync-room-statuses-every-60s": {
            "task": "heizung.sync_room_statuses",
            "schedule": 60.0,
            "options": {"queue": "heizung_default"},
        },
        # Sprint 20g (H-6 T10): erinnert an einen gesetzten PIN_SHA — Mail
        # nach sieben Tagen, danach woechentlich. Stuendlich aus demselben
        # Grund wie der Import-Waechter darueber: ein fester Tages-Slot ist
        # ein Slot, der verpasst werden kann (§5.79). Die Mail bremst
        # ``alert_throttle``, der Takt hier ist nur die Gelegenheit.
        #
        # Versetzt zu :20, damit nicht beide Waechter dieselbe Minute
        # belegen — kein Lastproblem, nur lesbarere Logs.
        "pin-reminder-hourly": {
            "task": "heizung.check_pin_reminder",
            "schedule": crontab(minute=40),
            "options": {"queue": "heizung_default"},
        },
    },
)


@worker_process_init.connect
def _reset_engine_per_worker(**_: object) -> None:
    """Sprint 9.6b: jeder Forked-Worker-Prozess bekommt eine FRISCHE
    SQLAlchemy-Engine. Sonst teilen sich Worker-Forks den DB-Pool des
    Master-Process — Connections funktionieren im neuen Event-Loop nicht
    (``Future attached to a different loop``).

    Strategie: alten Engine im Pool dispose-en + neue Async-Engine + neue
    Session-Factory. Die ``heizung.db``-Modul-Variablen ``engine`` und
    ``SessionLocal`` werden ersetzt, damit alle Imports automatisch die
    neue Engine sehen.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from heizung import db as db_module

    settings = get_settings()
    asyncio.run(db_module.engine.dispose())
    db_module.engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=False,
        pool_recycle=900,
    )
    db_module.SessionLocal = async_sessionmaker(db_module.engine, expire_on_commit=False)
    logger.info("celery worker: SQLAlchemy-Engine reset (forked process)")
