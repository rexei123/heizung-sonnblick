"""Event-Log-Helper fuer Off-Pipeline-Audit-Events (Sprint 9.11y).

Engine-Pipeline-LayerSteps werden weiterhin direkt in
``tasks.engine_tasks._evaluate_room_async`` als ``EventLog``-Rows
inserted (Sprint 9.5 / 9.10d). Dieser Service-Helper deckt nur
**Off-Pipeline-Events** ab — Audit-Eintraege, die NICHT zur Engine-
Schicht-Reihenfolge gehoeren:

- ``inferred_window_observation``: AE-47 §Passiver Trigger,
  Sprint 9.11y. Detected via ``rules.inferred_window.detect_inferred_window``.

Off-Pipeline-Events bekommen jeweils eine eigene ``evaluation_id``
(neuer UUID pro Event), damit sie im event_log nicht mit Engine-
Evaluations vermischt werden. ``setpoint_in == setpoint_out`` ist
ein Marker, dass das Event keine Setpoint-Aenderung ausgeloest hat
(passive Beobachtung).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from heizung.models.enums import CommandReason, EventLogLayer
from heizung.models.event_log import EventLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.rules.inferred_window import InferredWindowResult


async def log_inferred_window_event(
    session: AsyncSession,
    result: InferredWindowResult,
) -> None:
    """Schreibt einen passiven Inferred-Window-Eintrag ins event_log.

    Inserted, kein Commit — der Caller (``_evaluate_room_async``)
    macht den Commit gemeinsam mit der regulaeren Engine-Eval.

    ``setpoint_in == setpoint_out`` markiert das Event als rein
    observational. ``reason=INFERRED_WINDOW`` und
    ``layer=INFERRED_WINDOW_OBSERVATION`` machen den Eintrag in der
    event_log-Tabelle eindeutig identifizierbar (z.B. fuer Diagnose-
    Queries oder kuenftige Notification-Skripte).
    """
    eval_id = uuid.uuid4()
    setpoint_decimal: Decimal | None = (
        Decimal(result.setpoint_c) if result.setpoint_c is not None else None
    )
    session.add(
        EventLog(
            time=result.detected_at,
            room_id=result.room_id,
            evaluation_id=eval_id,
            layer=EventLogLayer.INFERRED_WINDOW_OBSERVATION,
            setpoint_in=setpoint_decimal,
            setpoint_out=setpoint_decimal,
            reason=CommandReason.INFERRED_WINDOW,
            details={
                "detail": f"delta_c={result.delta_c}",
                "delta_c": str(result.delta_c),
                "devices_observed": list(result.devices_observed),
            },
        )
    )
