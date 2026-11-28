"""Abreise ueberschritten — ein Hinweis fuer die Rezeption (27.11.2026).

**Der Fall, den das Handbuch seit dem 25.10.2026 beschreibt** (Artikel
„Abreise verschiebt sich"): ein Gast bleibt laenger, niemand aendert das
Abreisedatum, und die Steuerung setzt das Zimmer am urspruenglichen
Abreisetag auf **frei**. Der Gast kommt abends in ein kuehles Zimmer
zurueck, obwohl niemand etwas falsch gemacht hat.

Das Handbuch sagt, was zu tun ist. Es sagt nicht, **wann** — und genau da
faellt der Fall durch: wer das Datum vergisst, liest den Artikel nicht.

Was dieser Dienst liefert
-------------------------

Die Zimmer, deren **Abreise in den letzten Stunden verstrichen** ist und
fuer die **keine** neue Belegung laeuft. Das sind an einem normalen Tag
eine Handvoll — die Abreisen des Vormittags —, und die Rezeption sieht
daran, welche Liste sie noch einmal ansehen sollte.

**Dazu, je Zimmer, ein Zeichen.** Es gibt zwei Spuren, die ein Gast in
einem Zimmer hinterlaesst, das die Steuerung fuer leer haelt:

* **Drehrad.** Jemand hat am Thermostat gedreht, und die Steuerung hat
  die Verstellung **abgelehnt**, weil das Zimmer als frei gilt (AE-58,
  das OCCUPIED-Tor). Diese Ablehnungen stehen seit Sprint 12a als
  ``manual_override_blocked`` im ``event_log`` (Paragraph 5.52) — sie
  waren bisher nur ein Diagnosepfad, und sie sind der beste Hinweis, den
  die Anlage auf einen anwesenden Gast hat.
* **Uebersteuerung.** Die Rezeption hat nach der Abreise eine
  Wunschtemperatur gesetzt. Dann weiss sie es schon — und der Hinweis
  sagt ihr, dass die **Belegung** trotzdem falsch steht.

**Das Zeichen filtert nicht, es sortiert.** Ein Zimmer ohne Spur ist
nicht geklaert, sondern unbeobachtet: die meisten Gaeste drehen nicht am
Thermostat. Wer die Liste auf „mit Zeichen" verkuerzt, baut einen
Melder, der genau die stillen Faelle verschweigt — und das sind die
teuren (Paragraph 5.55).

Was dieser Dienst **nicht** tut
-------------------------------

* **Er verschickt nichts.** Vorgabe des Betreibers: Hinweis auf dem
  Dashboard, keine Mail. Eine Abreise ist ein Alltagsereignis; eine Mail
  je Abreise waere nach drei Tagen ein Filter im Postfach — und dann ist
  auch der Alarm weg, der etwas bedeutet (Paragraph 5.79).
* **Er greift nicht in die Steuerung ein.** Das Zimmer bleibt auf dem
  Frei-Wert. Ob der Gast noch da ist, weiss nur die Rezeption; eine
  Anlage, die aus einer Vermutung weiterheizt, heizt leere Zimmer
  (Paragraph 0 S5).
* **Er aendert die Belegung nicht.** Das Datum zu verlaengern ist eine
  Entscheidung mit Folgen fuer Abrechnung und naechste Anreise.

Das Fenster
-----------

``ABREISE_FENSTER_H`` (24 h). Kuerzer waere ein Hinweis, der mittags
verschwindet, bevor der Gast abends im kuehlen Zimmer steht; laenger
waere eine Liste, die mit den Tagen waechst und sich nicht abarbeiten
laesst. Die Zahl steht hier und nicht in den Settings, weil es keinen
Fall gibt, in dem zwei Haeuser sie verschieden brauchen — kommt er, zieht
sie in die Settings um.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import EventLogLayer
from heizung.models.event_log import EventLog
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room

#: Wie lange eine verstrichene Abreise im Hinweis bleibt.
ABREISE_FENSTER_H: int = 24

#: Was ein Zimmer als „vielleicht noch belegt" kennzeichnet.
Zeichen = Literal["drehrad", "uebersteuerung", "keines"]


@dataclass(frozen=True, slots=True)
class AbreiseBefund:
    """Ein Zimmer, dessen Abreise verstrichen ist."""

    room_id: int
    #: Zimmernummer bzw. Bereichsname — die Form, in der die Rezeption
    #: das Zimmer kennt.
    zimmer: str
    #: Die Abreise, die verstrichen ist (UTC).
    abgereist_am: datetime
    #: Wie lange sie her ist, in ganzen Stunden, abgerundet. 0 heisst
    #: „in dieser Stunde".
    stunden_her: int
    zeichen: Zeichen

    @property
    def vielleicht_belegt(self) -> bool:
        """Ob eine Spur auf einen anwesenden Gast deutet.

        **Kein Urteil, nur eine Spur.** ``False`` heisst nicht „das Zimmer
        ist leer", sondern „wir haben nichts gesehen" — und die meisten
        Gaeste drehen nicht am Thermostat.
        """
        return self.zeichen != "keines"


async def lies_abreisen(
    session: AsyncSession, *, jetzt: datetime, fenster_h: int = ABREISE_FENSTER_H
) -> list[AbreiseBefund]:
    """Die Zimmer mit verstrichener Abreise, juengste zuerst.

    ``jetzt`` ist ein Argument und kein ``datetime.now()`` im Rumpf — aus
    demselben Grund wie in ``relais_verlauf``: ein Beleg mit festem
    Fenster bleibt morgen noch gruen (Paragraph 5.59).
    """
    ab = jetzt - timedelta(hours=fenster_h)

    # Die **juengste** verstrichene Abreise je Zimmer. ``is_active``: eine
    # zurueckgezogene Belegung ist keine Abreise, sondern eine Korrektur.
    letzte = (
        select(
            Occupancy.room_id.label("room_id"),
            func.max(Occupancy.check_out).label("abgereist_am"),
        )
        .where(Occupancy.is_active.is_(True))
        .where(Occupancy.check_out < jetzt)
        .where(Occupancy.check_out >= ab)
        .group_by(Occupancy.room_id)
        .subquery()
    )

    # Ein Zimmer, fuer das **jetzt** eine Belegung laeuft, ist kein Fall:
    # dort ist der Gast angemeldet, und die Steuerung heizt.
    laeuft = (
        select(Occupancy.room_id)
        .where(Occupancy.is_active.is_(True))
        .where(Occupancy.check_in <= jetzt)
        .where(Occupancy.check_out > jetzt)
        .scalar_subquery()
    )

    zeilen = (
        await session.execute(
            select(letzte.c.room_id, letzte.c.abgereist_am, Room.number)
            .join(Room, Room.id == letzte.c.room_id)
            .where(letzte.c.room_id.not_in(laeuft))
            .order_by(letzte.c.abgereist_am.desc())
        )
    ).all()
    if not zeilen:
        return []

    raeume = [int(r.room_id) for r in zeilen]
    abgereist = {int(r.room_id): r.abgereist_am for r in zeilen}

    # --- Spur 1: eine abgelehnte Drehrad-Verstellung nach der Abreise ---
    #
    # ``manual_override_blocked`` ist der Off-Pipeline-Eintrag aus Sprint
    # 12a (Paragraph 5.52): ein Gast hat gedreht, und das OCCUPIED-Tor hat
    # die Verstellung verworfen. Fuer diesen Hinweis ist das die
    # aussagekraeftigste Zeile der ganzen Datenbank — jemand war im
    # Zimmer, nachdem es als frei gefuehrt wurde.
    gedreht: set[int] = set()
    for room_id, zeit in (
        await session.execute(
            select(EventLog.room_id, func.max(EventLog.time))
            .where(EventLog.room_id.in_(raeume))
            .where(EventLog.layer == EventLogLayer.MANUAL_OVERRIDE_BLOCKED)
            .where(EventLog.time >= ab)
            .group_by(EventLog.room_id)
        )
    ).all():
        if zeit is not None and zeit >= abgereist[int(room_id)]:
            gedreht.add(int(room_id))

    # --- Spur 2: eine laufende Uebersteuerung, gesetzt nach der Abreise --
    uebersteuert: set[int] = set()
    for room_id, zeit in (
        await session.execute(
            select(ManualOverride.room_id, func.max(ManualOverride.created_at))
            .where(ManualOverride.room_id.in_(raeume))
            .where(ManualOverride.revoked_at.is_(None))
            .where(ManualOverride.expires_at > jetzt)
            .group_by(ManualOverride.room_id)
        )
    ).all():
        if zeit is not None and zeit >= abgereist[int(room_id)]:
            uebersteuert.add(int(room_id))

    befunde: list[AbreiseBefund] = []
    for zeile in zeilen:
        room_id = int(zeile.room_id)
        # Das Drehrad zuerst: es ist die Spur des **Gastes**, die
        # Uebersteuerung die der Rezeption. Wo beides vorliegt, ist die
        # erste die Nachricht.
        if room_id in gedreht:
            zeichen: Zeichen = "drehrad"
        elif room_id in uebersteuert:
            zeichen = "uebersteuerung"
        else:
            zeichen = "keines"
        befunde.append(
            AbreiseBefund(
                room_id=room_id,
                zimmer=str(zeile.number or room_id),
                abgereist_am=zeile.abgereist_am,
                stunden_her=int((jetzt - zeile.abgereist_am).total_seconds() // 3600),
                zeichen=zeichen,
            )
        )
    return befunde
