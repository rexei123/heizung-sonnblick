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
        "heizung.tasks.override_cleanup_tasks",
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
    # Sprint 9.6 Race-Condition-Mitigation: Engine-Tasks bekommen einen
    # 30s-Lock per Redis-SETNX. Wird im Engine-Task selbst gesetzt, hier
    # nur die Default-Soft-Time-Limit fuer alle Tasks.
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
