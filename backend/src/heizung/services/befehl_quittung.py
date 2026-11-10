"""``control_command.acknowledged_at`` fuellen — reine Buchfuehrung (Sprint 25, T2).

**Der Befund.** Die Spalte existiert seit Sprint 9.2 und wurde **nie
gesetzt**. Jeder Befehl in der Datenbank sieht damit aus wie „nie
angekommen", und zwar auch die 604.000, die angekommen sind. Eine Spalte,
die immer leer ist, ist keine fehlende Information — sie ist eine falsche.

**Keine Logik haengt daran.** Kein Tor, keine Wiederholung, keine
Alarmschwelle, kein Einfluss auf Hysterese, Abgleich oder Engine. Das ist
die Vorgabe des Betreibers, und sie hat einen Grund: zu ueberwachen ist
der **Zustand** des Geraets, nicht der Lebenslauf eines Befehls. Wer an
eine Quittung eine Wiederholung haengt, baut einen zweiten Regelkreis
neben die Engine.

Der Nutzen ist Diagnose — und Ehrlichkeit.

**Was als Quittung gilt.** Ein Uplink, der den gesendeten Wert meldet:
der Sollwert im Periodenbericht (``0x81``) oder die ausdrueckliche
Antwort (``0x52``). Beides laeuft durch dieselbe Funktion hier, weil es
dieselbe Aussage ist: *das Geraet steht auf dem Wert, den wir geschickt
haben.*

**Der juengste offene Befehl mit diesem Wert, nicht jeder.** Sonst
quittiert ein zufaellig passender Periodenbericht einen Befehl, der nie
zugestellt wurde — und die Spalte waere wieder falsch, nur in die andere
Richtung. Festlegung des Betreibers (Brief T2).

**Die Folge, und sie ist gewollt:** stehen zwei Befehle mit demselben
Wert offen, bleibt der aeltere offen. Er wurde vom juengeren ueberholt,
und niemand hat ihn je einzeln bestaetigt. Das als „auch quittiert" zu
schreiben waere eine Annahme, keine Beobachtung.

**Die Zeitgrenze ist nicht Kosmetik.** ``sent_to_gateway_at <=
gemeldet_um``: ein Uplink kann keinen Befehl bestaetigen, der nach ihm
hinausging. Ohne diese Bedingung quittiert bei einem Downlink, der im
selben Augenblick rausgeht, der Uplink **von vorher** — dieselbe Falle,
die am 07.11.2026 im Ack-Fenster von ``device_adapter`` steckte.

**Class A, und deshalb dauert es.** Ein Vicki holt den Downlink erst im
Fenster nach einem eigenen Uplink ab; die Bestaetigung traegt dann die
**uebernaechste** Meldung. Zwischen Befehl und Quittung liegen damit
regelmaessig zehn bis zwanzig Minuten, und ein ``acknowledged_at``, das
eine Minute nach ``sent_to_gateway_at`` liegt, waere der verdaechtige
Fall, nicht der normale.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.control_command import ControlCommand

logger = logging.getLogger(__name__)


async def quittiere(
    session: AsyncSession,
    *,
    device_id: int,
    gemeldet_c: Decimal,
    gemeldet_um: datetime,
) -> int | None:
    """Setzt ``acknowledged_at`` am juengsten offenen Befehl mit diesem Wert.

    :param gemeldet_c: der Sollwert, den das Geraet meldet.
    :param gemeldet_um: Zeitpunkt des Uplinks. Dieselbe Zeitquelle wie im
        Rest des Pfads — die **Gateway-Zeit** (``uplink.time``), mit
        Rueckfall auf die Serverzeit. Belegt in
        ``tests/test_phantom_override_20fb.py``.
    :return: ``id`` des quittierten Befehls, oder ``None`` wenn keiner
        passt. ``None`` ist der **Normalfall** und kein Fehler: die
        meisten Uplinks melden einen Wert, zu dem kein offener Befehl
        steht.

    Der Vergleich laeuft als ``numeric`` in der Datenbank, nicht als Text.
    ``21.00`` und ``21.0`` sind damit derselbe Wert — ein
    Zeichenketten-Vergleich waere hier genau der Fehler, der am
    07.11.2026 die CI von #393 rot gemacht hat.
    """
    stmt = (
        select(ControlCommand)
        .where(ControlCommand.device_id == device_id)
        # Diese Bedingung ist gegen die Zeitgrenze darunter **redundant**:
        # ``NULL <= gemeldet_um`` ist in SQL nicht wahr, ein nie gesendeter
        # Befehl faellt also ohnehin heraus. Sie bleibt trotzdem stehen,
        # weil sie die Absicht **sagt** — wer die Abfrage liest, soll
        # „nur gesendete Befehle" nicht aus dem NULL-Verhalten eines
        # Vergleichs erschliessen muessen. Belegt am 08.11.2026: die
        # Mutationsprobe, die diese Zeile entfernt, bleibt gruen, weil die
        # zweite Bedingung traegt.
        .where(ControlCommand.sent_to_gateway_at.is_not(None))
        .where(ControlCommand.sent_to_gateway_at <= gemeldet_um)
        .where(ControlCommand.acknowledged_at.is_(None))
        .where(ControlCommand.target_setpoint == gemeldet_c)
        .order_by(ControlCommand.sent_to_gateway_at.desc())
        .limit(1)
    )
    befehl = (await session.execute(stmt)).scalars().first()
    if befehl is None:
        return None

    befehl.acknowledged_at = gemeldet_um
    await session.flush()
    logger.info(
        "befehl_quittiert command_id=%s device_id=%s wert=%s gesendet=%s quittiert=%s",
        befehl.id,
        device_id,
        gemeldet_c,
        befehl.sent_to_gateway_at.isoformat() if befehl.sent_to_gateway_at else None,
        gemeldet_um.isoformat(),
    )
    return befehl.id
