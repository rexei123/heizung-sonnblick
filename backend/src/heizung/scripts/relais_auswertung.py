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

Die **Ansicht** kommt ohnehin: der Relais-Verlauf auf der Geraeteseite
(Diagramm, Tabelle je Tag, CSV) steht als eigener Punkt im Auftrag. Er
beantwortet „wie lief es gestern", nicht „reicht das Geraet".

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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

# Siehe ``funkqualitaet``: der Guard trennt den CLI-Aufruf vom Import
# durch die Tests.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

import asyncio  # noqa: E402

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.enums import DeviceKind  # noqa: E402
from heizung.models.heating_zone import HeatingZone  # noqa: E402
from heizung.services.event_log import SollStand  # noqa: E402

logger = logging.getLogger("relais_auswertung")

ZONE = "Europe/Vienna"


@dataclass(frozen=True, slots=True)
class Stunde:
    """Eine Stunde einer Zone: wie lange ein, wie warm, wie gewollt."""

    stunde: datetime
    ein_prozent: int | None
    erfasste_minuten: int
    einschaltungen: int
    ist_mittel: Decimal | None
    ist_min: Decimal | None
    ist_max: Decimal | None
    soll: Decimal | None

    @property
    def abstand(self) -> Decimal | None:
        """Soll minus Ist. Positiv heisst „zu kalt"."""
        if self.soll is None or self.ist_mittel is None:
            return None
        return self.soll - self.ist_mittel


@dataclass(frozen=True, slots=True)
class Zonenbericht:
    zone_id: int
    room_id: int
    zone_name: str
    zimmer: str
    relais: list[str]
    stunden: list[Stunde]

    @property
    def anteil_gesamt(self) -> int | None:
        """Einschaltanteil ueber alle Stunden, nach erfasster Zeit gewichtet.

        **Nicht der Mittelwert der Stundenwerte.** Eine Stunde mit zehn
        erfassten Minuten wuerde darin so schwer zaehlen wie eine volle,
        und am Rand des Fensters sind die Stunden immer kurz.
        """
        minuten = sum(s.erfasste_minuten for s in self.stunden if s.ein_prozent is not None)
        if not minuten:
            return None
        gewichtet = sum(
            s.ein_prozent * s.erfasste_minuten for s in self.stunden if s.ein_prozent is not None
        )
        return round(gewichtet / minuten)

    @property
    def stunden_mit_heizwunsch(self) -> list[Stunde]:
        """Die Stunden, in denen das Ist unter dem Soll lag.

        **Nur diese zaehlen fuer die Panel-Frage.** Eine Stunde, in der
        der Raum warm genug war, sagt nichts ueber die Leistung des
        Panels — dort ist ein niedriger Anteil richtig.
        """
        return [s for s in self.stunden if (a := s.abstand) is not None and a > 0]


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


async def _zonen_mit_relais(session: AsyncSession) -> list[tuple[HeatingZone, list[Device]]]:
    """Alle Zonen, in denen ein **in Betrieb genommenes** Relais haengt.

    ``commissioned_at IS NOT NULL``: ein provisioniertes, aber nicht
    freigegebenes Relais schaltet nicht, und seine Zone gehoert nicht in
    eine Auswertung ueber Heizleistung.
    """
    zeilen = (
        await session.execute(
            select(Device, HeatingZone)
            .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
            .where(Device.kind == DeviceKind.RELAY)
            .where(Device.retired_at.is_(None))
            .where(Device.commissioned_at.is_not(None))
            .order_by(HeatingZone.id, Device.id)
        )
    ).all()

    je_zone: dict[int, tuple[HeatingZone, list[Device]]] = {}
    for geraet, zone in zeilen:
        eintrag = je_zone.setdefault(zone.id, (zone, []))
        eintrag[1].append(geraet)
    return list(je_zone.values())


_ANTEIL_SQL = text("""
    WITH roh AS (
        SELECT rr.time,
               rr.relay_on,
               lead(rr.time) OVER (PARTITION BY rr.device_id ORDER BY rr.time) AS bis,
               lag(rr.relay_on) OVER (PARTITION BY rr.device_id ORDER BY rr.time) AS vorher
        FROM relay_reading rr
        WHERE rr.device_id = ANY(:device_ids)
          AND rr.time >= :ab AND rr.time < :bis_fenster
          AND rr.relay_on IS NOT NULL
    )
    SELECT date_trunc('hour', time) AS stunde,
           sum(CASE WHEN relay_on THEN
                 EXTRACT(EPOCH FROM (least(bis, time + :deckel) - time))
               ELSE 0 END) AS ein_s,
           sum(EXTRACT(EPOCH FROM (least(bis, time + :deckel) - time))) AS gesamt_s,
           count(*) FILTER (WHERE relay_on AND vorher IS false) AS einschaltungen
    FROM roh
    WHERE bis IS NOT NULL
    GROUP BY 1
    ORDER BY 1
""")

_IST_SQL = text("""
    SELECT date_trunc('hour', sr.time) AS stunde,
           round(avg(sr.temperature), 2) AS mittel,
           min(sr.temperature) AS kleinst,
           max(sr.temperature) AS groesst
    FROM sensor_reading sr
    WHERE sr.device_id = ANY(:device_ids)
      AND sr.time >= :ab AND sr.time < :bis_fenster
      AND sr.temperature IS NOT NULL
    GROUP BY 1
    ORDER BY 1
""")

_SOLL_SQL = text("""
    SELECT DISTINCT ON (date_trunc('hour', el.time))
           date_trunc('hour', el.time) AS stunde,
           el.setpoint_out,
           el.details -> 'downlink_zone_status' AS zonen
    FROM event_log el
    WHERE el.room_id = :room_id
      AND el.layer = 'hard_clamp'
      AND el.time >= :ab AND el.time < :bis_fenster
    ORDER BY date_trunc('hour', el.time), el.time DESC
""")

#: Obergrenze fuer die Dauer, die **einer** Meldung zugerechnet wird.
#: Das Relais meldet alle zehn Minuten; eine Luecke von Stunden darf
#: nicht als „die ganze Zeit ein" zaehlen. Fuenfzehn Minuten lassen eine
#: verspaetete Meldung durch und schneiden echte Luecken ab.
_DECKEL = timedelta(minutes=15)


async def _ist_geraete(session: AsyncSession, zone_id: int) -> list[int]:
    """Die Fuehler der Zone — einschliesslich ``measure_only``.

    Der Regler nimmt das Zonen-Aggregat ueber genau diese Geraete; eine
    andere Auswahl hier waere eine zweite Wahrheit ueber den Istwert.
    """
    return list(
        (
            await session.execute(
                select(Device.id)
                .where(Device.heating_zone_id == zone_id)
                .where(Device.kind != DeviceKind.RELAY)
                .where(Device.retired_at.is_(None))
            )
        )
        .scalars()
        .all()
    )


def _soll_der_stunde(row: object, room_id: int, zone_id: int) -> Decimal | None:
    """Zimmerwert und Zonenwert einer Zeile, nach der Regel des Reglers.

    Der ``SollStand`` wird hier nur **gebaut**; die Vorrangregel steht in
    ``SollStand.fuer`` und nirgends sonst.
    """
    setpoint_out = getattr(row, "setpoint_out", None)
    zonen = getattr(row, "zonen", None)
    je_zone: dict[int, int] = {}
    if isinstance(zonen, list):
        for eintrag in zonen:
            if not isinstance(eintrag, dict):
                continue
            zid = eintrag.get("zone_id")
            wert = eintrag.get("setpoint_c")
            if (
                isinstance(zid, int)
                and not isinstance(zid, bool)
                and isinstance(wert, int)
                and not isinstance(wert, bool)
            ):
                je_zone[zid] = wert
    stand = SollStand(
        je_zimmer={room_id: setpoint_out},
        je_zone={room_id: je_zone} if je_zone else {},
    )
    return stand.fuer(room_id, zone_id)


async def _bericht(
    session: AsyncSession,
    zone: HeatingZone,
    relais: list[Device],
    *,
    ab: datetime,
    bis: datetime,
) -> Zonenbericht:
    ids = [g.id for g in relais]
    anteil = {
        r.stunde: r
        for r in (
            await session.execute(
                _ANTEIL_SQL,
                {"device_ids": ids, "ab": ab, "bis_fenster": bis, "deckel": _DECKEL},
            )
        ).all()
    }
    fuehler = await _ist_geraete(session, zone.id)
    ist = (
        {
            r.stunde: r
            for r in (
                await session.execute(
                    _IST_SQL, {"device_ids": fuehler, "ab": ab, "bis_fenster": bis}
                )
            ).all()
        }
        if fuehler
        else {}
    )
    soll = {
        r.stunde: r
        for r in (
            await session.execute(
                _SOLL_SQL, {"room_id": zone.room_id, "ab": ab, "bis_fenster": bis}
            )
        ).all()
    }

    stunden: list[Stunde] = []
    for h in sorted(set(anteil) | set(ist) | set(soll)):
        a = anteil.get(h)
        i = ist.get(h)
        s = soll.get(h)
        gesamt = float(a.gesamt_s or 0) if a else 0.0
        stunden.append(
            Stunde(
                stunde=h,
                ein_prozent=(round(100.0 * float(a.ein_s or 0) / gesamt) if a and gesamt else None),
                erfasste_minuten=round(gesamt / 60),
                einschaltungen=int(a.einschaltungen or 0) if a else 0,
                ist_mittel=i.mittel if i else None,
                ist_min=i.kleinst if i else None,
                ist_max=i.groesst if i else None,
                soll=_soll_der_stunde(s, zone.room_id, zone.id) if s else None,
            )
        )

    zimmer_nummer = ""
    if zone.room_id:
        zimmer_nummer = (
            await session.execute(
                text("SELECT number FROM room WHERE id = :r"), {"r": zone.room_id}
            )
        ).scalar() or ""

    return Zonenbericht(
        zone_id=zone.id,
        room_id=zone.room_id,
        zone_name=zone.name or f"Zone {zone.id}",
        zimmer=str(zimmer_nummer),
        relais=[g.label or g.dev_eui for g in relais],
        stunden=stunden,
    )


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
