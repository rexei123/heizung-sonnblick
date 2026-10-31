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

Sprint 14e FU-2 ergaenzt Read-Helper fuer die ZoneCard-Anzeige des
zuletzt von der Engine als HARD_CLAMP geschriebenen Setpoints
(``latest_hard_clamp_setpoint_per_room``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from heizung.models.enums import CommandReason, EventLogLayer
from heizung.models.event_log import EventLog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.rules.inferred_window import InferredWindowResult


# Sprint 14e FU-2: Frische-Fenster, jenseits dessen die HARD_CLAMP-Row als
# "veraltet" gilt (keine Anzeige im ZoneCard). 1 h ist >> 60s-Heartbeat
# (engine_tasks.py:255), bleibt aber kurz genug, dass ein steckender Tick
# auffaellt.
_HARD_CLAMP_FRESHNESS = timedelta(hours=1)


async def latest_hard_clamp_setpoint_per_room(
    session: AsyncSession,
    room_ids: Iterable[int],
) -> dict[int, Decimal | None]:
    """Pro Zimmer den juengsten ``HARD_CLAMP``-Setpoint im 1h-Fenster.

    DISTINCT ON (room_id) … ORDER BY time DESC — Index-Pfad
    ``ix_event_log_room_time`` (models/event_log.py:100). Filter:

    - ``layer == HARD_CLAMP`` (Engine-Final-Setpoint, AE-55 P1; deckt sowohl
      die normale Pipeline als auch den Sommer-Fast-Path, §5.32-konsistent).
    - ``time > now - 1h`` (``_HARD_CLAMP_FRESHNESS``) — ohne diesen Filter
      laesst ein totes Zimmer einen Stale-Setpoint stehen.
    - ``room_id = ANY(:room_ids)``.

    Quelle des Wertes ist die Top-Level-Spalte ``EventLog.setpoint_out``
    (Numeric(4,1), models/event_log.py:80) — NICHT die ``details``-JSONB.

    Rueckgabe: ``dict[room_id, Decimal | None]``. Rooms ohne Eintrag im
    Frische-Fenster fehlen im Resultat-dict (Konsument leitet auf ``None``).
    Decimal wird unveraendert durchgereicht, Quantisierung passiert in der
    Engine (``rules.engine._quantize``) — wir spiegeln den persistierten Wert.
    """
    ids = list(room_ids)
    if not ids:
        return {}

    since = datetime.now(tz=UTC) - _HARD_CLAMP_FRESHNESS
    stmt = (
        select(EventLog.room_id, EventLog.setpoint_out)
        .where(EventLog.layer == EventLogLayer.HARD_CLAMP)
        .where(EventLog.room_id.in_(ids))
        .where(EventLog.time > since)
        .order_by(EventLog.room_id, EventLog.time.desc())
        .distinct(EventLog.room_id)
    )
    rows = (await session.execute(stmt)).all()
    return {row.room_id: row.setpoint_out for row in rows}


async def latest_hard_clamp_zone_setpoints(
    session: AsyncSession,
    room_ids: Iterable[int],
) -> dict[int, dict[int, int]]:
    """Pro Zimmer die Sollwerte **je Zone** aus der juengsten HARD_CLAMP-Zeile.

    Rueckgabe ``{room_id: {zone_id: setpoint_c}}``. Ein fehlendes Zimmer
    oder eine fehlende Zone heisst „dazu steht nichts in der Zeile" — der
    Aufrufer faellt dann auf den Zimmerwert aus
    :func:`latest_hard_clamp_setpoint_per_room` zurueck.

    **Warum es diese Funktion gibt** (Befund des Betreibers, 31.10.2026).
    Der Trace hielt bis dahin nur den **Zimmer**-Sollwert fest. Eine
    **Zonen**-Uebersteuerung stand nirgends, und deshalb zeigten
    Zimmerliste, Zonenkarte und Verlauf 21, waehrend das Geraet 23 fuhr.
    Der Wert, den die Anzeige sucht, ist der, den der Dispatch je Zone
    verwendet hat — und den schreibt er seit demselben Tag in
    ``details['downlink_zone_status']``.

    Gelesen wird **dieselbe Zeile**, aus der der Zimmerwert kommt: gleiche
    Form, gleiches Frischefenster, gleiche Sortierung. Damit koennen
    Zimmerwert und Zonenwert nicht aus verschiedenen Auswertungen stammen.

    **Ausgepackt wird in Python, nicht in SQL.** Die Zonen stehen als
    JSON-**Array** in der Zeile (es ist der Zustandsbericht je Zone, und
    der hat noch andere Felder), und ein ``jsonb_array_elements`` dafuer
    waere mehr Abfrage fuer dieselbe Information. Je Zimmer kommt genau
    eine Zeile, die Liste hat so viele Eintraege wie das Zimmer Zonen —
    das sind zwei.

    **Beim Deploy ist das Ergebnis leer**, bis der erste Engine-Lauf je
    Zimmer durch ist (hoechstens eine Minute, das Frischefenster ist eine
    Stunde). Bis dahin greift der Rueckfall und es bleibt bei der alten
    Anzeige — kein Loch, nur der alte Fehler eine Minute laenger.
    """
    ids = list(room_ids)
    if not ids:
        return {}

    since = datetime.now(tz=UTC) - _HARD_CLAMP_FRESHNESS
    stmt = (
        select(EventLog.room_id, EventLog.details["downlink_zone_status"].label("zonen"))
        .where(EventLog.layer == EventLogLayer.HARD_CLAMP)
        .where(EventLog.room_id.in_(ids))
        .where(EventLog.time > since)
        .order_by(EventLog.room_id, EventLog.time.desc())
        .distinct(EventLog.room_id)
    )
    ergebnis: dict[int, dict[int, int]] = {}
    for room_id, zonen in (await session.execute(stmt)).all():
        if not isinstance(zonen, list):
            continue
        je_zone: dict[int, int] = {}
        for eintrag in zonen:
            # Zeilen aus der Zeit vor dem 31.10.2026 haben kein
            # ``setpoint_c``. Sie werden uebersprungen und nicht mit einer
            # Null gefuellt: „steht nicht da" muss vom Wert 0 zu
            # unterscheiden bleiben, sonst zeigte die Liste Frostschutz.
            if not isinstance(eintrag, dict):
                continue
            zone_id = eintrag.get("zone_id")
            wert = eintrag.get("setpoint_c")
            # ``not isinstance(..., bool)``, weil ``isinstance(True, int)``
            # wahr ist. Ein JSON-``true`` wuerde sonst als Sollwert 1
            # durchgehen — dieselbe Falle wie in
            # ``tests/test_geraetegrenzen_ende_zu_ende.py``.
            if (
                isinstance(zone_id, int)
                and not isinstance(zone_id, bool)
                and isinstance(wert, int)
                and not isinstance(wert, bool)
            ):
                je_zone[zone_id] = wert
        if je_zone:
            ergebnis[int(room_id)] = je_zone
    return ergebnis


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
