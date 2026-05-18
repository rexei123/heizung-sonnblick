"""Sprint 11 T6 — Health-Alarm-Stub (AE-53 Stufe-2 + Stufe-3).

Heute: strukturierter Logger-Aufruf, der in journalctl / Container-Log
landet und nach ``dev_eui`` / ``reason`` grep-bar ist. Kein SMTP-Versand
— das ist eigener Sprint nach Heizperiode.

Konsument: ``_compute_health_state_async`` (health_tasks.py) ruft
``emit_health_alert`` fuer jede silent-Transition auf
(Stufe-3-Trigger laut AE-53).

Heutige Bedeutung "Stufe":

- **Stufe 1:** Device degraded (2-24h offline). Heute KEIN Alarm —
  sichtbar nur im ``device.health_state``. UI-Anzeige in Sprint 14.
- **Stufe 2:** Device silent durch offline > 24h. Logger-Alarm mit
  ``reason="offline_24h"``.
- **Stufe 3:** Device silent durch >= 10 implausible Readings in 24h
  (AE-53 Stufe-3-Trigger). Logger-Alarm mit
  ``reason="implausible_readings_24h"``.

Idempotenz: ``silent_transitions``-Liste aus T5 enthaelt bauartbedingt
nur ``previous != "silent" AND new_state == "silent"``-Uebergaenge,
stabile silent-Devices sind nicht in der Liste — also kein Re-Mail-
Sturm beim 5-min-Beat-Tick. Bei spaeterem SMTP-Swap muss der Helper
ggf. zusaetzlich pro dev_eui dedupliziert werden (z.B. Redis-Key
``health_alert_sent:{dev_eui}`` mit TTL); heute out-of-scope.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def emit_health_alert(
    *,
    level: int,
    device_id: int,
    dev_eui: str,
    reason: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Emittiert einen strukturierten WARNING-Log-Event.

    Args:
        level: ``2`` (offline_24h) oder ``3`` (implausible_readings_24h).
        device_id: Device-Primary-Key fuer DB-Korrelation.
        dev_eui: Device-EUI fuer Container-Log-grep.
        reason: ``"offline_24h"`` oder ``"implausible_readings_24h"`` —
            die Strings sind verbindlich (kommen aus AE-53 + T5).
        context: Optionaler Zusatz-Kontext (z.B. counter-Wert,
            last_uplink-Timestamp). Heute optional, in T7-Sprint-
            Abschlussbericht ggf. erweitert.
    """
    logger.warning(
        "health_alert",
        extra={
            "level": level,
            "device_id": device_id,
            "dev_eui": dev_eui,
            "reason": reason,
            "context": context or {},
        },
    )
