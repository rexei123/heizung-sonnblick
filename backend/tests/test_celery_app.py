"""Sprint 9.1 — Smoke-Tests fuer Celery-App + Stub-Task.

Kein Worker-Container noetig: ``task_always_eager = True`` laesst
Tasks synchron im aufrufenden Thread laufen.
"""

from __future__ import annotations

import pytest

from heizung.celery_app import app
from heizung.tasks.engine_tasks import evaluate_room


@pytest.fixture
def eager_celery() -> None:
    """Celery in Eager-Mode schalten — kein Broker noetig."""
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True


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


def test_evaluate_room_stub_returns_dict(eager_celery: None) -> None:  # noqa: ARG001
    """Stub liefert room_id + Status zurueck — Smoke fuer Sprint 9.4 Trigger."""
    result = evaluate_room.delay(42).get(timeout=5)
    assert result["room_id"] == 42
    assert result["status"] == "stub"
    assert result["sprint"] == "9.1"


def test_evaluate_room_callable_directly(eager_celery: None) -> None:  # noqa: ARG001
    """Direktaufruf ohne .delay() funktioniert (z.B. fuer Pytest oder REPL)."""
    result = evaluate_room.run(99)
    assert result["room_id"] == 99
