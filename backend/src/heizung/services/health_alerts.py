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
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def emit_health_alert(
    *,
    level: int,
    device_id: int,
    dev_eui: str,
    reason: str,
    device_name: str | None = None,
    room_name: str | None = None,
    zone_name: str | None = None,
    triggered_at: datetime | None = None,
    last_uplink_at: datetime | None = None,
    implausible_count_24h: int | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Emittiert einen strukturierten WARNING-Log-Event.

    Args:
        level: ``2`` (offline_24h) oder ``3`` (implausible_readings_24h).
        device_id: Device-Primary-Key fuer DB-Korrelation.
        dev_eui: Device-EUI fuer Container-Log-grep.
        reason: ``"offline_24h"`` oder ``"implausible_readings_24h"`` —
            die Strings sind verbindlich (kommen aus AE-53 + T5).
        device_name: Geraete-Bezeichnung (``device.label``) fuer den
            spaeteren Mail-Betreff. ``None`` wenn unbenannt.
        room_name: Zimmer-Nummer/-Name (``room.number``) via JOIN.
        zone_name: Heizzonen-Name (``heating_zone.name``) via JOIN.
        triggered_at: Zeitpunkt der Health-Eval (UTC), die den Alarm
            ausgeloest hat.
        last_uplink_at: Letztes Uplink-Reading des Devices (UTC).
        implausible_count_24h: Implausible-Counter-Stand (Stufe-3-Trigger).
        context: Optionaler Zusatz-Kontext (Backward-Compat-Slot).

    Sprint 14c T3 (additiv): ``device_name``..``implausible_count_24h``
    ergaenzt — alle keyword-only + optional, kein Breaking Change. Damit
    erreicht der Logger das 10/10-Soll-Feld-Set fuer den spaeteren
    SMTP-Versand (Phase-0-Audit Paket C). Re-Mail-Dedupe
    (``health_alert_sent:{dev_eui}``) bleibt Backlog.
    """
    logger.warning(
        "health_alert",
        extra={
            "level": level,
            "device_id": device_id,
            "dev_eui": dev_eui,
            "reason": reason,
            "device_name": device_name,
            "room_name": room_name,
            "zone_name": zone_name,
            "triggered_at": triggered_at.isoformat() if triggered_at is not None else None,
            "last_uplink_at": last_uplink_at.isoformat() if last_uplink_at is not None else None,
            "implausible_count_24h": implausible_count_24h,
            "context": context or {},
        },
    )
