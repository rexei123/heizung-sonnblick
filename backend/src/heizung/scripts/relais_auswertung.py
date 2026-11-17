r"""Einschaltdauer und Ist/Soll je Relais-Zone, Stunde fuer Stunde (15.11.2026).

**Wofuer.** Der Betreiber ueberlegt, ein zweites Panel fuer die Rezeption
zu kaufen. Die Frage dahinter ist „haelt ein Panel die 23 Grad", und sie
ist heute **nicht beantwortbar**: am 14./15.11. lief das Panel nur 60 bis
67 Prozent der Zeit, weil der Relais-Timer nach 30 Minuten ablief und die
Mindestpause danach weitere zehn Minuten hielt. Eine Messung gegen diese
Steuerung wuerde dem Geraet zuschreiben, was in der Steuerung liegt.

Dieses Werkzeug liefert die beiden Zahlen, an denen die Entscheidung
haengt, und es liefert sie **nebeneinander**: den Einschaltanteil und den
Abstand zwischen Ist und Soll. Steigt der Anteil nach dem Nachsetzen des
Timers Richtung 100 und bleibt das Ist trotzdem unter dem Soll, ist das
Panel zu schwach. Bleibt der Anteil niedrig, ist die Steuerung noch nicht
fertig und die Frage noch nicht reif.

Aufruf (Prod-Container heisst ``deploy-api-1``):

    docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung
    docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --stunden 72
    docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --seit "2026-11-16 10:00"

**PowerShell (lokal)**, mit der ``srv``-Funktion aus RUNBOOK Paragraph 4:

    srv 'docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --stunden 48'

``--seit`` ist **Ortszeit** (Europe/Vienna), weil der Mensch sie so
aufschreibt. Ohne Angabe gilt ``--stunden`` (Vorgabe 24).

**Es wird nichts gesendet und nichts geschrieben.** Dieses Werkzeug
liest.

Warum ein Werkzeug und keine Seite
----------------------------------

Die Entscheidung ueber ein Panel faellt einmal, nach zwei bis drei Tagen
Beobachtung, und sie braucht Zahlen zum Weitergeben — keine Ansicht zum
taeglichen Hinsehen. Ein Werkzeug kostet keine Oberflaeche, keine
e2e-Tests und keine Kachel, die danach fuer immer dasteht; seine Ausgabe
laesst sich in eine Nachricht kopieren. Dasselbe Muster wie
``funkqualitaet`` (Paragraph 10au), und aus demselben Grund.

Die **Ansicht** ist seit dem 17.11.2026 da: der Relais-Verlauf auf der
Geraeteseite (Diagramm, Tabelle je Tag, CSV). Er beantwortet „wie lief es
gestern", nicht „reicht das Geraet" — und er rechnet **nicht noch
einmal**: die Rechnung steht seither in ``services/relais_verlauf``, und
dieses Werkzeug liest sie von dort. Was hier bleibt, ist die Ausgabe fuer
den Menschen: ein Fenster, eine Tabelle je Zone, die Panel-Frage darunter.

Wie der Sollwert gelesen wird
-----------------------------

Aus derselben ``hard_clamp``-Zeile und mit derselben Vorrangregel wie im
Regler: steht in der Zeile ein Wert fuer **diese Zone**
(``downlink_zone_status[].setpoint_c``), gilt er; sonst der Zimmerwert
(``setpoint_out``). Die Regel selbst steht **nicht** hier, sondern in
``SollStand.fuer`` — dieses Werkzeug baut je Stunde einen ``SollStand``
und fragt ihn. Zwei Rechnungen fuer denselben Sollwert waeren zwei
Wahrheiten, und genau daran lag der Fehler, den der Betreiber am
15.11.2026 gemeldet hat (Paragraph 5.53).

Was die Zahlen nicht sagen
--------------------------

**Der Einschaltanteil ist zeitgewichtet und hat die Auflösung der
Meldungen.** Das Relais meldet alle zehn Minuten; ein Wechsel wird
frueheste zehn Minuten spaeter sichtbar. Die Phasengrenzen liegen also
bis zu zehn Minuten neben der Wirklichkeit, die Dauern stimmen im Mittel.
Ein Fenster ohne jede Meldung erscheint als Lücke und nicht als 0
Prozent — eine Null waere eine Behauptung ueber ein Geraet, von dem wir
nichts gehoert haben.

**Das Ist ist das Zonen-Aggregat**, also der Mittelwert der Fuehler
dieser Zone, einschliesslich der Fuehler auf „nur messen". In der
Rezeption und in der Bar ist das je **ein** Vicki (056 bzw. 027); faellt
er aus, steht in der Zeile ein Strich, und der Regler schaltet in dieser
Lage zwangsweise ab.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

# Siehe ``funkqualitaet``: der Guard trennt den CLI-Aufruf vom Import
# durch die Tests.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

import asyncio  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.services import relais_verlauf  # noqa: E402

# **Die Rechnung steht nicht mehr hier**, sondern in
# ``services/relais_verlauf`` — seit dem 17.11.2026, weil die Ansicht auf
# der Geraeteseite dieselben Zahlen zeigt und zwei Rechnungen fuer
# denselben Einschaltanteil zwei Wahrheiten waeren (§5.53).
#
# Die Verlagerung ist **verhaltensneutral** (§5.46/§5.47), und der Beleg
# dafuer sind die Tests dieses Werkzeugs: sie sind unveraendert
# geblieben und rufen weiterhin diese Namen. Deshalb stehen sie hier als
# ausdrueckliche Weitergabe — auch ``Stunde`` und ``_soll_der_stunde``,
# die das Werkzeug selbst nicht mehr braucht.
Stunde = relais_verlauf.Stunde
Zonenbericht = relais_verlauf.Zonenbericht
_bericht = relais_verlauf.bericht
_soll_der_stunde = relais_verlauf.soll_der_stunde
_zonen_mit_relais = relais_verlauf.zonen_mit_relais

logger = logging.getLogger("relais_auswertung")

ZONE = "Europe/Vienna"


def _ortszeit(wert: datetime) -> str:
    return wert.astimezone(ZoneInfo(ZONE)).strftime("%d.%m. %H:%M")


def _parse_seit(wert: str) -> datetime:
    """``--seit`` als **Ortszeit** lesen (dieselbe Falle wie Paragraph 5.65)."""
    roh = datetime.fromisoformat(wert)
    if roh.tzinfo is None:
        roh = roh.replace(tzinfo=ZoneInfo(ZONE))
    return roh.astimezone(UTC)


def _zahl(wert: Decimal | None, stellen: int = 1) -> str:
    if wert is None:
        return "—"
    return f"{wert:.{stellen}f}"


def _drucke(bericht: Zonenbericht) -> None:
    print()
    print(f"=== {bericht.zimmer} / {bericht.zone_name} — Relais: {', '.join(bericht.relais)}")
    print()
    print("Stunde         ein%   min  Einsch.   Ist    (min–max)      Soll   Abstand")
    print("-" * 76)
    for s in bericht.stunden:
        anteil = "—" if s.ein_prozent is None else f"{s.ein_prozent:>3}%"
        spanne = f"({_zahl(s.ist_min)}–{_zahl(s.ist_max)})"
        print(
            f"{_ortszeit(s.stunde):<14} {anteil:>5} {s.erfasste_minuten:>4} "
            f"{s.einschaltungen:>7}   {_zahl(s.ist_mittel):>5} {spanne:>14} "
            f"{_zahl(s.soll):>6} {_zahl(s.abstand):>8}"
        )

    print()
    heiz = bericht.stunden_mit_heizwunsch
    gesamt = bericht.anteil_gesamt
    print(f"Einschaltanteil ueber das Fenster: {'—' if gesamt is None else f'{gesamt} %'}")
    print(f"Einschaltungen:                    {sum(s.einschaltungen for s in bericht.stunden)}")
    print(f"Stunden mit Heizwunsch (Ist<Soll): {len(heiz)} von {len(bericht.stunden)}")
    if heiz:
        anteile = [s.ein_prozent for s in heiz if s.ein_prozent is not None]
        abstaende = [a for s in heiz if (a := s.abstand) is not None]
        if anteile:
            print(f"  davon Einschaltanteil:           {min(anteile)} bis {max(anteile)} %")
        if abstaende:
            print(f"  groesster Abstand zum Soll:      {_zahl(max(abstaende))} K")
        print()
        print("  **Die Zahlen, an denen die Panel-Frage haengt.** Laeuft das")
        print("  Panel in diesen Stunden nahe 100 Prozent und bleibt das Ist")
        print("  trotzdem unter dem Soll, ist es zu schwach. Bleibt der Anteil")
        print("  unter etwa 80 Prozent, bremst die Steuerung und die Frage ist")
        print("  noch nicht reif.")


async def _lade(args: argparse.Namespace) -> int:
    ab = (
        _parse_seit(args.seit)
        if args.seit
        else datetime.now(tz=UTC) - timedelta(hours=args.stunden)
    )
    bis = datetime.now(tz=UTC)

    async with SessionLocal() as session:
        zonen = await _zonen_mit_relais(session)
        if not zonen:
            print("Keine Zone mit einem in Betrieb genommenen Relais gefunden.")
            return 0
        print(f"Fenster: {_ortszeit(ab)} bis {_ortszeit(bis)} (Ortszeit {ZONE})")
        for zone, relais in zonen:
            _drucke(await _bericht(session, zone, relais, ab=ab, bis=bis))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="relais_auswertung",
        description="Einschaltdauer und Ist/Soll je Relais-Zone, Stunde fuer Stunde.",
    )
    parser.add_argument("--seit", help='Beginn in ORTSZEIT, z. B. "2026-11-16 10:00".')
    parser.add_argument(
        "--stunden", type=int, default=24, help="Fenster in Stunden, wenn --seit fehlt. Vorgabe 24."
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return _verteile(args)


def _verteile(args: argparse.Namespace) -> int:
    """Startet den Lauf — und nur das (Paragraph 5.14, zweiter Event-Loop)."""
    return asyncio.run(_lade(args))


if __name__ == "__main__":
    sys.exit(main())
