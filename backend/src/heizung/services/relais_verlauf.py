r"""Relais-Verlauf: Einschaltdauer, Ist/Soll, Energie — je Stunde und je Tag.

**Woher der Rumpf dieses Moduls kommt.** Die Rechnung stand ab dem
15.11.2026 in ``scripts/relais_auswertung`` und war dort ein Werkzeug
fuer eine einmalige Frage („haelt ein Panel die 23 Grad"). Der Auftrag
vom 16.11.2026 verlangt dieselben Zahlen als **Ansicht** auf der
Geraeteseite. Zwei Rechnungen fuer denselben Einschaltanteil waeren zwei
Wahrheiten (Paragraph 5.53) — und die eine, die niemand ansieht, waere
nach dem ersten Nachziehen falsch.

Die Verlagerung ist **verhaltensneutral** (Paragraph 5.46/5.47): Namen,
Signaturen und SQL sind unveraendert uebernommen, das Werkzeug importiert
sie von hier. Der Beleg dafuer sind die fuenfzehn Tests von
``test_relais_auswertung``, die **unveraendert** gruen bleiben; sie rufen
weiterhin ``werkzeug._bericht``, ``werkzeug.Stunde`` und
``werkzeug._zonen_mit_relais``.

Neu in diesem Modul, und nur neu:

* **Heizdauer in Minuten** je Stunde (``ein_minuten``). Der Anteil in
  Prozent stand schon da; die Minuten sind die Zahl, die der Betreiber
  weitergibt, und sie aus Prozent und erfassten Minuten
  zurueckzurechnen hiesse, zweimal zu runden.
* **Energie** je Stunde, aus dem Geraetezaehler (siehe unten).
* **Tageszeilen**, in **Ortszeit** gebuendelt, aus denselben Stunden.
* Das Fenster ``30d`` neben ``24h`` und ``7d``.

Die Energie, und warum sie nicht einfach eine Differenz ist
-----------------------------------------------------------

``relay_reading.energy_wh`` ist ein **Zaehlerstand**, nicht der Verbrauch
seit der letzten Meldung. Er laeuft bei 0xFFFFFFFF ueber, der Befehl
``0x26`` setzt ihn auf 0, und nach einem Geraetetausch beginnt er bei 0
(Kopf von ``models/relay_reading``). Wer ihn wie eine Temperatur
differenziert, bekommt bei jedem dieser drei Ereignisse einen
**negativen** Verbrauch.

Gerechnet wird deshalb die Summe der **positiven** Spruenge; ein
negativer Sprung wird **gezaehlt und nicht addiert**, und die Zahl steht
in der Antwort (``ruecksprunge``). Dasselbe Muster wie bei
``services/paketverlust``, das Geraete-Neustarts neben dem Verlust
ausweist, statt sie darin zu verstecken.

**Der Fall ist in diesem Haus noch nie eingetreten** (gemessen am
17.11.2026, beide Relais, ganze Historie: kein einziger Ruecksprung — der
Zaehler ueberlebte sogar den Stromstoss beim Rejoin von 108 um 08:39).
Behandelt wird er trotzdem, weil das Gegenteil einen stillen Fehler
ergibt: ein Ruecksprung ohne Behandlung macht aus einem Tagesverbrauch
eine negative Zahl oder — bei ``sum`` ueber gemischte Vorzeichen — eine
zu kleine, und niemand sieht, warum.

**Wo die Energie innerhalb einer Luecke liegt, wissen wir nicht.** Der
Sprung zwischen zwei Meldungen wird der Stunde der **ersten** zugerechnet
(dieselbe Richtung wie beim Einschaltanteil, der mit ``lead`` nach vorne
blickt). Ueber das Fenster ist die Summe damit richtig; innerhalb einer
Meldungsluecke ist die Verteilung eine Annahme. Die Luecke selbst ist in
derselben Zeile sichtbar: ``erfasste_minuten`` sagt, wie viel der Stunde
ueberhaupt belegt ist.

Was die Zahlen nicht sagen
--------------------------

Unveraendert gegenueber dem Werkzeug: der Einschaltanteil hat die
Auflösung der Meldungen (alle zehn Minuten), eine Stunde ohne Meldung
erscheint als Luecke und nicht als 0 Prozent, und das Ist ist das
Zonen-Aggregat einschliesslich der Fuehler auf „nur messen" — dieselbe
Auswahl, mit der der Regler rechnet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.heating_zone import HeatingZone
from heizung.services.event_log import SollStand

#: Die Fenster der Ansicht. Die Eimer sind **immer Stunden** — auch im
#: 24-Stunden-Fenster, obwohl das Relais alle zehn Minuten meldet.
#:
#: Grund: die Stunde ist die Einheit, in der die Rechnung belegt ist
#: (``test_relais_auswertung``), und 24 Balken sind eine Ansicht, die ein
#: Mensch liest. Zehn-Minuten-Eimer waeren 144 Balken, von denen jeder
#: aus **einer** Meldung besteht — also ein Zustand und keine Dauer.
Bereich = Literal["24h", "7d", "30d"]

BEREICHE: dict[Bereich, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


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
    #: Heizdauer in Minuten. ``None`` heisst „keine Meldung in dieser
    #: Stunde" — dieselbe Unterscheidung wie bei ``ein_prozent``, und aus
    #: demselben Grund: eine 0 waere eine Behauptung ueber ein Geraet,
    #: von dem wir nichts gehoert haben.
    ein_minuten: int | None = None
    #: Verbrauch in Wh aus den positiven Spruengen des Geraetezaehlers.
    #: ``None`` heisst „der Zaehler sagt dazu nichts" (alte Zeilen ohne
    #: ``energy_wh``, oder nur eine Meldung in der Stunde).
    energie_wh: int | None = None
    #: Negative Spruenge des Zaehlers in dieser Stunde. Nicht addiert,
    #: sondern gezaehlt — siehe Modulkopf.
    ruecksprunge: int = 0

    @property
    def abstand(self) -> Decimal | None:
        """Soll minus Ist. Positiv heisst „zu kalt"."""
        if self.soll is None or self.ist_mittel is None:
            return None
        return self.soll - self.ist_mittel


@dataclass(frozen=True, slots=True)
class Tag:
    """Ein **Ortszeit**-Kalendertag, aus den Stunden dieses Tages.

    **Aus den Stunden und nicht aus einer zweiten Abfrage.** Ein eigenes
    ``date_trunc('day', ...)`` waere eine zweite Rechnung fuer denselben
    Einschaltanteil, und es waere dazu noch in UTC: der Tag des Hotels
    beginnt um 23:00 UTC (Winter) bzw. 22:00 (Sommer), und eine
    Tageszeile, die um 01:00 Ortszeit beginnt, beantwortet keine Frage,
    die jemand gestellt hat.
    """

    tag: date
    ein_minuten: int
    erfasste_minuten: int
    #: Zeitgewichtet, wie ``Zonenbericht.anteil_gesamt`` — nicht der
    #: Mittelwert der Stundenwerte.
    ein_prozent: int | None
    einschaltungen: int
    energie_wh: int | None
    ruecksprunge: int
    #: Mittel der **Stundenmittel**, nicht der einzelnen Messwerte. Der
    #: Unterschied ist eine Stunde mit wenigen Meldungen, die hier so
    #: schwer zaehlt wie eine volle; fuer eine Tageszeile ist das die
    #: Auflösung, die reicht.
    ist_mittel: Decimal | None
    ist_min: Decimal | None
    ist_max: Decimal | None
    soll_mittel: Decimal | None


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

    @property
    def ein_minuten_gesamt(self) -> int:
        return sum(s.ein_minuten or 0 for s in self.stunden)

    @property
    def einschaltungen_gesamt(self) -> int:
        return sum(s.einschaltungen for s in self.stunden)

    @property
    def energie_wh_gesamt(self) -> int | None:
        """Verbrauch ueber das Fenster. ``None``, wenn keine Stunde etwas sagt.

        Eine 0 waere hier eine Aussage („es lief, hat aber nichts
        verbraucht"), und die ist bei einem Zaehler, der noch nie
        gemeldet hat, nicht gedeckt.
        """
        werte = [s.energie_wh for s in self.stunden if s.energie_wh is not None]
        return sum(werte) if werte else None

    @property
    def ruecksprunge_gesamt(self) -> int:
        return sum(s.ruecksprunge for s in self.stunden)

    def tage(self, tz_name: str) -> list[Tag]:
        """Die Stunden zu **Ortszeit**-Kalendertagen gebuendelt."""
        return tage_aus_stunden(self.stunden, tz_name)


def tage_aus_stunden(stunden: list[Stunde], tz_name: str) -> list[Tag]:
    """Tageszeilen aus Stundenzeilen, in der Zone ``tz_name``.

    Die Stunde traegt ihren UTC-Anfang; der Kalendertag ist der **lokale**
    Tag dieses Augenblicks. In der Umstellungsnacht hat ein Tag damit 23
    bzw. 25 Stundenzeilen — richtig, und der Grund, warum ``erfasste_minuten``
    in der Zeile steht statt angenommen zu werden.
    """
    tz = ZoneInfo(tz_name)
    je_tag: dict[date, list[Stunde]] = {}
    for s in stunden:
        je_tag.setdefault(s.stunde.astimezone(tz).date(), []).append(s)

    zeilen: list[Tag] = []
    for tag in sorted(je_tag):
        gruppe = je_tag[tag]
        # Prozent und Minuten als Paare, damit die Gewichtung dieselbe
        # ist wie in ``anteil_gesamt``: eine Stunde mit zehn erfassten
        # Minuten zaehlt ein Sechstel einer vollen.
        anteile = [(s.ein_prozent, s.erfasste_minuten) for s in gruppe if s.ein_prozent is not None]
        minuten = sum(m for _, m in anteile)
        ist = [s.ist_mittel for s in gruppe if s.ist_mittel is not None]
        min_werte = [s.ist_min for s in gruppe if s.ist_min is not None]
        max_werte = [s.ist_max for s in gruppe if s.ist_max is not None]
        soll = [s.soll for s in gruppe if s.soll is not None]
        energie = [s.energie_wh for s in gruppe if s.energie_wh is not None]
        zeilen.append(
            Tag(
                tag=tag,
                ein_minuten=sum(s.ein_minuten or 0 for s in gruppe),
                erfasste_minuten=minuten,
                ein_prozent=(round(sum(p * m for p, m in anteile) / minuten) if minuten else None),
                einschaltungen=sum(s.einschaltungen for s in gruppe),
                energie_wh=sum(energie) if energie else None,
                ruecksprunge=sum(s.ruecksprunge for s in gruppe),
                ist_mittel=(_mittel(ist) if ist else None),
                ist_min=min(min_werte) if min_werte else None,
                ist_max=max(max_werte) if max_werte else None,
                soll_mittel=(_mittel(soll) if soll else None),
            )
        )
    return zeilen


def _mittel(werte: list[Decimal]) -> Decimal:
    """Mittelwert auf eine Stelle — die Auflösung, in der Temperaturen stehen."""
    return (sum(werte, Decimal(0)) / len(werte)).quantize(Decimal("0.1"))


async def zonen_mit_relais(session: AsyncSession) -> list[tuple[HeatingZone, list[Device]]]:
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
               rr.energy_wh,
               lead(rr.time) OVER (PARTITION BY rr.device_id ORDER BY rr.time) AS bis,
               lead(rr.energy_wh) OVER (PARTITION BY rr.device_id ORDER BY rr.time) AS energie_bis,
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
           count(*) FILTER (WHERE relay_on AND vorher IS false) AS einschaltungen,
           -- Nur **positive** Spruenge; ein Ruecksprung wird gezaehlt
           -- und nicht addiert (Modulkopf). ``sum`` ohne passende Zeile
           -- ist NULL und damit „der Zaehler sagt dazu nichts" — nicht 0.
           sum(CASE WHEN energie_bis > energy_wh THEN energie_bis - energy_wh END) AS energie_wh,
           count(*) FILTER (WHERE energie_bis < energy_wh) AS ruecksprunge
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


async def ist_geraete(session: AsyncSession, zone_id: int) -> list[int]:
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


def soll_der_stunde(row: object, room_id: int, zone_id: int) -> Decimal | None:
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


async def bericht(
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
    fuehler = await ist_geraete(session, zone.id)
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
                soll=soll_der_stunde(s, zone.room_id, zone.id) if s else None,
                # Die Minuten kommen aus ``ein_s`` und nicht aus
                # ``ein_prozent`` x ``erfasste_minuten``: der Prozentwert
                # ist schon gerundet, und zwei Rundungen uebereinander
                # ergeben bei kurzen Stunden Minuten, die es nicht gab.
                ein_minuten=(round(float(a.ein_s or 0) / 60) if a and gesamt else None),
                energie_wh=(int(a.energie_wh) if a and a.energie_wh is not None else None),
                ruecksprunge=int(a.ruecksprunge or 0) if a else 0,
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


@dataclass(frozen=True, slots=True)
class RelaisVerlauf:
    """Alles, was die Ansicht braucht — ohne dass sie etwas nachrechnet."""

    device_id: int
    zone_id: int
    zone_name: str
    zimmer: str
    #: Die Etiketten **aller** Relais der Zone, auch der anderen. Die
    #: Zahlen gelten fuer die Zone und nicht fuer ein Geraet: zwei Panels
    #: in einem Raum heizen gemeinsam, und ein Einschaltanteil je Geraet
    #: wuerde zu einer Summe verleiten, die 200 Prozent ergibt.
    relais: list[str]
    bereich: Bereich
    von: datetime
    bis: datetime
    timezone: str
    stunden: list[Stunde]
    tage: list[Tag]
    ein_minuten_gesamt: int
    anteil_gesamt: int | None
    einschaltungen_gesamt: int
    energie_wh_gesamt: int | None
    ruecksprunge_gesamt: int


async def lade_relais_verlauf(
    session: AsyncSession,
    *,
    geraet: Device,
    bereich: Bereich,
    tz_name: str,
    jetzt: datetime | None = None,
) -> RelaisVerlauf | None:
    """Der Verlauf der Zone, in der dieses Relais haengt.

    ``None`` heisst: das Relais hat keine Heizzone. Das ist kein Fehler,
    sondern der Zustand eines gerade angelegten Geraets — und auch der
    eines getauschten (``replace_device`` nimmt ``heating_zone_id``
    weg, RUNBOOK Paragraph 10x).

    ``jetzt`` ist ein Argument und kein ``datetime.now()`` im Rumpf, aus
    demselben Grund wie in ``room_history.lade_verlauf``: ein Beleg mit
    festem Fenster bleibt morgen noch gruen.

    Das Fenster ist halboffen (``>= von``, ``< bis``), damit eine Meldung
    in genau einer Stunde liegt — auch an der Grenze.
    """
    if geraet.heating_zone_id is None:
        return None
    zone = await session.get(HeatingZone, geraet.heating_zone_id)
    if zone is None:
        return None

    bis = jetzt if jetzt is not None else datetime.now(tz=UTC)
    von = bis - BEREICHE[bereich]

    # **Alle Relais der Zone**, nicht nur dieses: siehe ``relais``.
    geschwister = list(
        (
            await session.execute(
                select(Device)
                .where(Device.heating_zone_id == zone.id)
                .where(Device.kind == DeviceKind.RELAY)
                .where(Device.retired_at.is_(None))
                .order_by(Device.id)
            )
        )
        .scalars()
        .all()
    )
    if not any(g.id == geraet.id for g in geschwister):
        geschwister.append(geraet)

    b = await bericht(session, zone, geschwister, ab=von, bis=bis)
    return RelaisVerlauf(
        device_id=geraet.id,
        zone_id=b.zone_id,
        zone_name=b.zone_name,
        zimmer=b.zimmer,
        relais=b.relais,
        bereich=bereich,
        von=von,
        bis=bis,
        timezone=tz_name,
        stunden=b.stunden,
        tage=b.tage(tz_name),
        ein_minuten_gesamt=b.ein_minuten_gesamt,
        anteil_gesamt=b.anteil_gesamt,
        einschaltungen_gesamt=b.einschaltungen_gesamt,
        energie_wh_gesamt=b.energie_wh_gesamt,
        ruecksprunge_gesamt=b.ruecksprunge_gesamt,
    )
