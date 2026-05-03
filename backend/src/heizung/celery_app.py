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

from celery import Celery

from heizung.config import get_settings

_settings = get_settings()

# Celery-App-Singleton. ``include`` zeigt auf alle Module, in denen
# ``@app.task``-Dekoratoren leben — bisher nur engine_tasks (Stub).
app: Celery = Celery(
    "heizung",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["heizung.tasks.engine_tasks"],
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
)
