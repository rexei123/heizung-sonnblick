"""Sprint 9.1 + 9.4 — Celery-App + Task-Registry-Tests.

Sprint 9.1 hatte einen Stub-Task. Sprint 9.4-5 ersetzt durch echte
Engine-Logik mit DB-Zugriff — daher kann der Eager-Mode-Test nur
Registrierung pruefen, nicht das Run-Ergebnis (das braucht eine echte
Test-DB, wird in 9.6 Live-Test verifiziert).
"""

from __future__ import annotations

from heizung.celery_app import app


def test_celery_app_configured() -> None:
    """App existiert mit erwartetem Namen + Default-Queue."""
    assert app.main == "heizung"
    assert app.conf.task_default_queue == "heizung_default"
    assert app.conf.task_serializer == "json"
    assert app.conf.timezone == "UTC"
    assert app.conf.enable_utc is True


def test_evaluate_room_task_registered() -> None:
    """Task ist unter dem dokumentierten Namen registriert."""
    assert "heizung.evaluate_room" in app.tasks


def test_evaluate_room_task_has_retries_configured() -> None:
    """Sprint 9.4: max_retries=3 + default_retry_delay=10s."""
    task = app.tasks["heizung.evaluate_room"]
    assert task.max_retries == 3
    assert task.default_retry_delay == 10
