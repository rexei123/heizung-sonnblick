"""Engine-Celery-Tasks.

Sprint 9.1 (2026-05-03): Stub-Implementierung.
Sprint 9.3 wird ``evaluate_room`` mit echter Engine-Logik fuellen
(Layer 1 Base + Layer 5 Clamp + Hysterese als Walking Skeleton).
Sprint 9.7 fuegt ``evaluate_due_rooms`` als Celery-Beat-Periodic-Task hinzu.

Designgrund fuer Stub jetzt:
- API-Endpoints koennen schon ``evaluate_room.delay(room_id)`` aufrufen
  (Sprint 9.4 Trigger-Logik) ohne Crash.
- Celery-Worker-Container kann produktiv hochgefahren werden, Healthcheck
  ``celery inspect ping`` antwortet — Compose-Stack stabil.
"""

from __future__ import annotations

import logging
from typing import Any

from heizung.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="heizung.evaluate_room", bind=True, max_retries=3, default_retry_delay=10)
def evaluate_room(self: Any, room_id: int) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Re-evaluate Engine fuer einen Raum.

    Sprint-9.1-Stub: Loggt + returnt Status-Dict ohne DB-/MQTT-Zugriff.
    Sprint 9.3 fuellt mit echter Engine.evaluate(ctx) -> RuleResult.

    :param room_id: ID des Raums in der ``room``-Tabelle.
    :return: Dict mit room_id + Status + Sprint-Marker.
    """
    logger.info("evaluate_room stub aufgerufen room_id=%s", room_id)
    return {
        "room_id": room_id,
        "status": "stub",
        "sprint": "9.1",
        "message": "Engine-Logik kommt in Sprint 9.3+",
    }
