"""Funk-Empfang: eine Quelle für die Kachel und für den Totalausfall-Alarm.

**Der Anlass, 07.11.2026.** Eine Firewall-Regel auf Port 1883 hat die
Anlage **31 Minuten** ohne Messwerte stehen lassen. Das Gateway war in
Ordnung, ChirpStack meldete es als verbunden, und **kein einziger**
vorhandener Melder hat angeschlagen:

* Die Health-Stufe ``silent`` greift erst nach
  ``health_degraded_max_age_h`` (Vorgabe **3 h**).
* Der Funk-Wächter (Sprint 25 T6) urteilt bei zu wenigen Daten
  ``unbekannt`` — und genau das erzeugt ein Totalausfall.
* Die Kachel „Thermostate online" zählt ``device.health_state``, also
  dieselbe 3-Stunden-Grenze.

Gefunden wurde der Ausfall, weil jemand hingesehen hat.

Warum nicht der ChirpStack-Gateway-Status
-----------------------------------------

Vorgabe des Betreibers, und sie ist der Kern dieses Moduls: der
Gateway-Status prüft **das Gateway**, nicht **die Kette**. Am 07.11. war
das Gateway erreichbar und hätte grün gezeigt, während am Ende der Kette
null Meldungen ankamen.

Gelesen wird deshalb das **Ende** der Kette — ``sensor_reading``. Was
dort nicht ankommt, ist weg, unabhängig davon, welches Glied es verloren
hat.

Die zwei Zahlen
---------------

1. **Wann kam die letzte Meldung** — die Frage, die der Ausfall gestellt
   hat.
2. **Wie viele kamen in den letzten zehn Minuten** — die Frage, die eine
   *schleichende* Verschlechterung stellt. Bei über hundert Geräten im
   10-Minuten-Takt sind rund hundert normal; fünf wären ein Befund, den
   die erste Zahl nicht sieht.

Beide Abfragen sind billig, und das ist Absicht: die Kachel hängt an
jedem Seitenaufruf des Dashboards.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)

#: Das Zählfenster der zweiten Zahl. **Keine Einstellung** — die Zahl
#: steht als Text in der Kachel („Y Meldungen in 10 min"), und ein
#: verstellbares Fenster hinter einer festen Beschriftung wäre die
#: nächste §5.77-Stelle.
ZAEHLFENSTER_MIN: int = 10

Stufe = Literal["online", "verzoegert", "keine_meldungen", "unbekannt"]


@dataclass(frozen=True, slots=True)
class Funkempfang:
    """Der Zustand der Empfangskette, wie Kachel und Alarm ihn lesen."""

    letzte_meldung: datetime | None
    #: Alter der letzten Meldung in Minuten, abgerundet. ``None``, wenn es
    #: keine Meldung gibt.
    alter_min: int | None
    meldungen_zaehlfenster: int
    stufe: Stufe

    @property
    def ist_totalausfall(self) -> bool:
        """Nichts kommt mehr an — die Bedingung für den Alarm.

        ``unbekannt`` zählt **nicht** dazu: eine leere Datenbank ist ein
        frisch aufgesetztes Haus, kein Ausfall.
        """
        return self.stufe == "keine_meldungen"


def beurteile(
    *,
    letzte_meldung: datetime | None,
    meldungen: int,
    now: datetime,
    gruen_max_min: int,
    gelb_max_min: int,
) -> Funkempfang:
    """Urteil aus den zwei Zahlen — ohne Datenbank, ohne Uhr von außen.

    Reihenfolge verbindlich: ``unbekannt`` zuerst. Gibt es **gar keine**
    Meldung, ist das ein frisch aufgesetztes Haus und kein Ausfall; rot
    zu zeigen wäre eine Behauptung über eine Anlage, die es noch nicht
    gibt.
    """
    if letzte_meldung is None:
        return Funkempfang(None, None, meldungen, "unbekannt")

    alter = now - letzte_meldung
    alter_min = max(0, int(alter.total_seconds() // 60))

    # **Die gelbe Grenze ist exklusiv, die gruene inklusiv** — und das ist
    # kein Versehen, sondern aus den Tests gefallen. Die Vorgabe des
    # Betreibers lautet "ab 15 Minuten ohne Messwert eine Mail". Waere
    # auch die gelbe Grenze inklusiv, waere die Kachel bei genau 15:00
    # noch gelb, waehrend der Alarm mailt — und wer dann nachsieht, findet
    # eine gelbe Kachel zu einer roten Mail.
    #
    # Gruen bleibt inklusiv, weil es dort nichts kostet: bei
    # 10-Minuten-Takt und ueber hundert Geraeten schwankt das Alter der
    # juengsten Meldung um Sekunden, und eine Kachel, die bei 5:00 kippt
    # und bei 4:59 zurueckkippt, flackert.
    if alter <= timedelta(minutes=gruen_max_min):
        stufe: Stufe = "online"
    elif alter < timedelta(minutes=gelb_max_min):
        stufe = "verzoegert"
    else:
        stufe = "keine_meldungen"

    return Funkempfang(letzte_meldung, alter_min, meldungen, stufe)


async def lies_funkempfang(
    session: AsyncSession,
    *,
    gruen_max_min: int,
    gelb_max_min: int,
    now: datetime | None = None,
) -> Funkempfang:
    """Die zwei Zahlen aus ``sensor_reading``, dann das Urteil.

    **Beide Abfragen sind billig, und zwar aus verschiedenen Gründen.**

    ``max(time)`` auf einer TimescaleDB-Hypertable ist ein rückwärts
    laufender Index-Scan: der jüngste Chunk antwortet, die übrigen 189
    werden nicht angefasst. Das Zählfenster schließt über die
    Zeitbedingung alle Chunks bis auf den jüngsten aus.

    Das ist der Grund, warum hier **kein** Aggregat über sieben Tage
    steht — die Kachel hängt an jedem Seitenaufruf (vgl. AE-72, wo
    dieselbe Abwägung gemessen wurde).
    """
    jetzt = now or datetime.now(tz=UTC)

    letzte = await session.scalar(select(func.max(SensorReading.time)))
    meldungen = (
        await session.scalar(
            select(func.count()).where(
                SensorReading.time > jetzt - timedelta(minutes=ZAEHLFENSTER_MIN)
            )
        )
    ) or 0

    befund = beurteile(
        letzte_meldung=letzte,
        meldungen=int(meldungen),
        now=jetzt,
        gruen_max_min=gruen_max_min,
        gelb_max_min=gelb_max_min,
    )
    if befund.ist_totalausfall:
        logger.warning(
            "funkempfang keine_meldungen letzte=%s alter_min=%s meldungen=%s",
            befund.letzte_meldung,
            befund.alter_min,
            befund.meldungen_zaehlfenster,
        )
    return befund


# ---------------------------------------------------------------------------
# Mailtext für den Totalausfall
# ---------------------------------------------------------------------------


def betreff_alarm(befund: Funkempfang) -> str:
    return f"Heizung Sonnblick: keine Messwerte seit {befund.alter_min} Minuten"


def betreff_entwarnung() -> str:
    return "Heizung Sonnblick: Messwerte kommen wieder"


def nachricht_alarm(befund: Funkempfang, *, zeitzone: str) -> str:
    """Die Handlung zuerst, die Zahlen danach.

    Wer nachts geweckt wird, soll in der ersten Zeile lesen, was zu tun
    ist — und die Reihenfolge der Prüfschritte ist die aus dem Ausfall
    vom 07.11.: **zuerst das, was jemand gerade geändert hat.**
    """
    from zoneinfo import ZoneInfo

    letzte = (
        befund.letzte_meldung.astimezone(ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")
        if befund.letzte_meldung
        else "unbekannt"
    )
    return (
        f"Seit {befund.alter_min} Minuten kommt keine einzige Messung mehr an.\n"
        f"Letzte Meldung: {letzte}.\n\n"
        f"WAS ZU TUN IST — in dieser Reihenfolge\n"
        f"1. Wurde gerade etwas geaendert? Firewall, Port, ein Container, "
        f"ein Deploy. Am 07.11.2026 war es eine Firewall-Regel auf Port "
        f"1883, und das Gateway war dabei in Ordnung. Wenn ja: "
        f"zurueckbauen, nicht weiter diagnostizieren.\n"
        f"2. Kommen Meldungen an? RUNBOOK Paragraph 5.0a nennt den Befehl.\n"
        f"3. Gateway stromlos machen - RUNBOOK Paragraph 10ay.\n\n"
        f"WAS DIESE MELDUNG BEDEUTET\n"
        f"Sie liest das Ende der Kette, nicht den Gateway-Status. Ein "
        f"Gateway, das ChirpStack als verbunden meldet, kann trotzdem "
        f"keine Daten durchreichen - genau das war der 07.11.\n\n"
        f"Meldungen in den letzten {ZAEHLFENSTER_MIN} Minuten: "
        f"{befund.meldungen_zaehlfenster} (normal: rund hundert).\n"
    )


def nachricht_entwarnung(befund: Funkempfang, *, zeitzone: str) -> str:
    """Die Entwarnung ist Pflicht, nicht Hoeflichkeit.

    Ein Alarm ohne Entwarnung laesst den Empfaenger im Ungewissen, ob er
    noch handeln muss — und beim naechsten Mal liest er den Alarm
    langsamer (§5.79).
    """
    from zoneinfo import ZoneInfo

    jetzt = datetime.now(tz=ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")
    return (
        f"Es kommen wieder Messwerte an ({jetzt}).\n\n"
        f"Meldungen in den letzten {ZAEHLFENSTER_MIN} Minuten: "
        f"{befund.meldungen_zaehlfenster}.\n\n"
        f"Was die Entwarnung NICHT sagt: dass die Ursache behoben ist. "
        f"Sie sagt, dass Daten ankommen. Ob der Ausfall eine Spur "
        f"hinterlassen hat - fehlende Messwerte, ein Geraet auf einem "
        f"alten Sollwert, eine verlorene Drehung am Rad - steht in "
        f"RUNBOOK Paragraph 5.0a.\n"
    )
