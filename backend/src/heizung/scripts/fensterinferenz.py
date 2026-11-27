r"""Den Inferenz-Detektor gegen die Vergangenheit halten (27.11.2026).

**Wofuer.** Schritt 2 der Fenster-Erkennung ist gebaut, aber die Frage,
die ihn ausgeloest hat, ist damit nicht beantwortet: **findet er die 49
Einbrueche aus Zimmer 306 wieder?** Der Pruefsatz des Betreibers sind die
49 Faelle ab 1,5 Grad vom 05.11.2026, davon 37 mit oeffnendem Ventil
(``docs/status/2026-11-05-fenstererkennung-stand-lesbar.md``).

Dieses Werkzeug laesst den Detektor ueber einen **vergangenen** Zeitraum
laufen und zaehlt, was er gefunden haette. Erst damit ist die Vorgabe
„Pruefsatz 49 Ereignisse" ausfuehrbar.

Aufruf (Prod-Container heisst ``deploy-api-1``):

    docker exec deploy-api-1 python -m heizung.scripts.fensterinferenz
    docker exec deploy-api-1 python -m heizung.scripts.fensterinferenz --tage 30 --zimmer 306
    docker exec deploy-api-1 python -m heizung.scripts.fensterinferenz --tage 30 --schritt-min 5

**PowerShell (lokal)**, mit der ``srv``-Funktion aus RUNBOOK Paragraph 4:

    srv 'docker exec deploy-api-1 python -m heizung.scripts.fensterinferenz --tage 30 --zimmer 306'

**Es wird nichts gesendet und nichts geschrieben.** Dieses Werkzeug liest
— auch keine ``event_log``-Zeile. Was der Detektor im Betrieb schreibt,
schreibt er beim Tick; ein Probelauf, der Zeilen anlegt, haette die
Geschichte veraendert, gegen die er prueft.

Wie es rechnet, und was das kostet
----------------------------------

Der Detektor beantwortet „liegt **jetzt** ein Fall vor". Dieses Werkzeug
ruft ihn deshalb in Schritten durch den Zeitraum — alle
``--schritt-min`` Minuten, Vorgabe 10, also so oft, wie ein Vicki
ohnehin meldet.

Das ist langsam: dreissig Tage in Zehn-Minuten-Schritten sind 4320
Aufrufe je Zimmer, jeder mit drei Abfragen. **Und es ist die richtige
Form**, denn die Alternative waere, die Regel ein zweites Mal
hinzuschreiben — zwei Rechnungen fuer denselben Befund, von denen die
eine nach dem ersten Nachziehen falsch ist (Paragraph 5.53). Wer es
schneller braucht, nimmt ein kleineres Fenster, nicht eine zweite Regel.

**Treffer werden zu Episoden gebuendelt.** Ein offenes Fenster erzeugt
ueber eine halbe Stunde mehrere Treffer; gezaehlt werden soll das
Ereignis. Zwei Treffer, die weniger als ``--luecke-min`` auseinander
liegen, gehoeren zur selben Episode — dieselbe Buendelung wie in
``services/fenstererkennung.befund``, aus demselben Grund.

Was die Zahl nicht sagt
-----------------------

**Sie sagt nicht, ob ein Fenster offen war.** Sie sagt, wie oft der
Detektor es vermutet haette. Der Vergleich mit den 49 Einbruechen ist
deshalb der eigentliche Zweck: liegt die Zahl nah an 37, trifft der
Unterscheider; liegt sie bei 49, unterscheidet er nichts; liegt sie bei
3, ist die Schwelle zu hoch.

**Und sie sagt nichts ueber Gaeste.** Ein Fall mit aufgehendem Ventil
kann auch eine offene Zimmertuer, ein kaltes Nachbarzimmer oder ein
Fuehler in der Sonne sein. Deshalb ist Schritt 2 passiv.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import SessionLocal
from heizung.models.room import Room
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.rules.inferred_window import (
    INFERRED_WINDOW_DELTA_C_MIN,
    INFERRED_WINDOW_LOOKBACK_MIN,
    detect_inferred_window,
)

ZONE = DEFAULT_HOTEL_TIMEZONE


@dataclass(frozen=True, slots=True)
class Episode:
    """Ein zusammenhaengender Befund, aus mehreren Treffern gebuendelt."""

    von: datetime
    bis: datetime
    treffer: int
    delta_max: str
    ventil: str

    @property
    def dauer_min(self) -> int:
        return int((self.bis - self.von).total_seconds() // 60)


def _ortszeit(wann: datetime) -> str:
    return wann.astimezone(ZoneInfo(ZONE)).strftime("%d.%m. %H:%M")


async def _zimmer(session: AsyncSession, nummer: str | None) -> list[tuple[int, str]]:
    stmt = select(Room.id, Room.number).order_by(Room.number)
    if nummer:
        stmt = stmt.where(Room.number.ilike(f"%{nummer}%"))
    zeilen = (await session.execute(stmt)).all()
    return [(int(z.id), str(z.number)) for z in zeilen]


async def _episoden(
    session: AsyncSession,
    room_id: int,
    *,
    ab: datetime,
    bis: datetime,
    schritt_min: int,
    luecke_min: int,
) -> list[Episode]:
    """Laeuft den Zeitraum ab und buendelt die Treffer."""
    episoden: list[Episode] = []
    offen: list[tuple[datetime, str, str]] = []
    zeitpunkt = ab
    schritt = timedelta(minutes=schritt_min)
    luecke = timedelta(minutes=luecke_min)

    while zeitpunkt <= bis:
        treffer = await detect_inferred_window(session, room_id, zeitpunkt)
        if treffer is not None:
            ventil = f"{treffer.ventil_von}->{treffer.ventil_bis}"
            if offen and zeitpunkt - offen[-1][0] > luecke:
                episoden.append(_schliesse(offen))
                offen = []
            offen.append((zeitpunkt, str(treffer.delta_c), ventil))
        zeitpunkt += schritt

    if offen:
        episoden.append(_schliesse(offen))
    return episoden


def _schliesse(offen: list[tuple[datetime, str, str]]) -> Episode:
    """Fasst die Treffer einer Episode zusammen.

    ``delta_max`` ist der groesste Fall der Episode — die Zahl, die man
    beim Durchsehen sucht. Der Ventilweg stammt aus **derselben** Zeile:
    zwei Zahlen aus zwei Treffern nebeneinander waeren eine Aussage, die
    es so nie gab.
    """
    groesster = max(offen, key=lambda t: float(t[1]))
    return Episode(
        von=offen[0][0],
        bis=offen[-1][0],
        treffer=len(offen),
        delta_max=groesster[1],
        ventil=groesster[2],
    )


async def _lauf(args: argparse.Namespace) -> int:
    bis = datetime.now(tz=UTC)
    ab = bis - timedelta(days=args.tage)

    async with SessionLocal() as session:
        zimmer = await _zimmer(session, args.zimmer)
        if not zimmer:
            # Ein leerer Lauf saehe aus wie „nichts gefunden" — der
            # Unterschied zwischen „nichts zu melden" und „am falschen
            # Zimmer gesucht" ist der ganze Punkt (Paragraph 5.55).
            print(f"Kein Zimmer gefunden fuer '{args.zimmer}'. Abgebrochen.")
            return 2

        print(f"\nInferenz-Probelauf: {_ortszeit(ab)} bis {_ortszeit(bis)} Ortszeit ({ZONE})")
        print(
            f"Schwelle {INFERRED_WINDOW_DELTA_C_MIN} Grad, Lookback "
            f"{INFERRED_WINDOW_LOOKBACK_MIN} min, Schritt {args.schritt_min} min, "
            f"Buendelung {args.luecke_min} min"
        )
        print("Es wird nichts geschrieben und nichts gesendet.\n")

        gesamt = 0
        for room_id, nummer in zimmer:
            episoden = await _episoden(
                session,
                room_id,
                ab=ab,
                bis=bis,
                schritt_min=args.schritt_min,
                luecke_min=args.luecke_min,
            )
            gesamt += len(episoden)
            if not episoden:
                print(f"  {nummer}: keine Episode")
                continue
            print(f"  {nummer}: {len(episoden)} Episode(n)")
            for e in episoden:
                print(
                    f"      {_ortszeit(e.von)} bis {_ortszeit(e.bis)} "
                    f"({e.dauer_min:>3d} min, {e.treffer} Treffer) "
                    f"groesster Fall {e.delta_max} Grad, Ventil {e.ventil}"
                )

        print(f"\nZusammen {gesamt} Episode(n) in {len(zimmer)} Zimmer(n).")
        print(
            "Vergleich: der Pruefsatz des Betreibers sind 49 Einbrueche ab 1,5 "
            "Grad in Zimmer 306 ueber 30 Tage, davon 37 mit oeffnendem Ventil "
            "(Befund vom 05.11.2026)."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fensterinferenz",
        description=(
            "Laesst den passiven Inferenz-Detektor ueber die Vergangenheit laufen. Liest nur."
        ),
    )
    parser.add_argument("--zimmer", help="Teil der Zimmernummer. Ohne Angabe: alle.")
    parser.add_argument("--tage", type=int, default=7, help="Zeitraum in Tagen. Vorgabe 7.")
    parser.add_argument(
        "--schritt-min",
        type=int,
        default=10,
        help="Abstand der Aufrufe in Minuten. Vorgabe 10 (so oft meldet ein Vicki).",
    )
    parser.add_argument(
        "--luecke-min",
        type=int,
        default=30,
        help="Ab dieser Pause beginnt eine neue Episode. Vorgabe 30.",
    )
    args = parser.parse_args()
    if args.schritt_min < 1:
        print("--schritt-min muss mindestens 1 sein.")
        return 2
    if args.tage < 1:
        print("--tage muss mindestens 1 sein.")
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return _verteile(args)


def _verteile(args: argparse.Namespace) -> int:
    """Startet den Lauf — und nur das (Paragraph 5.14, zweiter Event-Loop)."""
    return asyncio.run(_lauf(args))


if __name__ == "__main__":
    sys.exit(main())
