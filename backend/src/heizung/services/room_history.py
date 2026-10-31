"""Zimmer-Verlauf: Messreihen je Heizzone, serverseitig zusammengefasst
(Sprint 21 A1).

**Erste Verwendung von ``time_bucket`` im Repo.** ``sensor_reading`` ist
eine Hypertable, die Funktion ist also da; CI faehrt dieselbe Datenbank wie
der Server (``timescale/timescaledb:latest-pg16`` in
``.github/workflows/backend-ci.yml``), ein Lauf gegen schlichtes Postgres
wuerde diese Abfrage nicht pruefen koennen. Ein Nachbau mit
``date_trunc`` plus Epoch-Arithmetik waere portabler und schwerer zu lesen
— portabel muessen wir nicht sein.

**Was je Eimer gerechnet wird, und warum unterschiedlich:**

* **Ist-Temperatur: Mittel** ueber die Geraete der Zone. AE-51 liest eine
  Zone als Mittelwert, und eine Anzeige, die anders rechnet als die Engine,
  erzeugt Diskussionen ueber die falsche Frage.
* **Gemeldeter Sollwert: Maximum** ueber die Geraete der Zone. Ein Sprung
  soll sichtbar sein, sobald er an **einem** Geraet ankommt. Das Mittel
  wuerde ihn verschleifen, solange ein zweites Geraet den Downlink noch
  nicht abgeholt hat — ein Vicki empfaengt nur im Fenster nach einem
  eigenen Uplink (§5.71), zwei Geraete einer Zone holen also nicht
  gleichzeitig ab. Das gilt seit dem 31.10.2026 fuer
  ``geraet_setpoint``; der **Sollwert** selbst kommt nicht mehr vom
  Geraet (siehe unten).

**Der Sollwert ist der der Engine, je Zone** — und der gemeldete Wert des
Geraets steht als eigene Reihe daneben, aber nur dort, wo er abweicht.

Hier stand bis zum 31.10.2026 das Gegenteil: der Sollwert kam aus
``sensor_reading.setpoint``, also vom Geraet, mit der Begruendung „gezeigt
wird, was am Heizkoerper gilt, nicht was die Engine wollte" (Sprint 21 A1,
AE-74). Der Zweck war richtig und ist geblieben: ein nicht angekommener
Downlink soll im Diagramm **sichtbar** sein statt geglaettet.

**Die Form war falsch, und zwei Befunde haben es gezeigt.**

Der erste, am 25.10.2026: im Zimmer „Bar" zeigte die Zone „Barbereich
(Soll)" durchgehend 10 °C, waehrend die Engine 21 bzw. 19 rechnete. Der
Wert war echt — er stand im Geraet, aus der Zeit der erzwungenen
Geraete-Sicherheit. Nur sagt er nichts mehr: eine Vicki mit der Rolle „nur
messen" bekommt **keine** Sollwerte (S7), ihr gespeicherter Wert friert in
dem Moment ein, in dem die Rolle gesetzt wird. Das wurde damals mit einem
Sonderfall fuer Zonen ohne Stellglied beantwortet.

Der zweite, am 30.10.2026 in Zimmer 107: „Schlafzimmer (Soll): 25,0 °C",
waehrend 23 galt. Der Gast hatte gedreht, die Sperre hatte die Drehung
abgewiesen — und das Diagramm zeigte den abgewiesenen Wert als Sollwert.
Dort gab es ein Stellglied, der Sonderfall griff also nicht.

Beide haben dieselbe Wurzel: **der Geraetewert beantwortet die Frage
„worauf steht es", und die Beschriftung versprach „worauf soll es
stehen".** Zwei Fragen, eine Linie. Deshalb jetzt zwei:

* ``setpoint`` ist der Engine-Sollwert **dieser Zone**, aus
  ``details['downlink_zone_status']`` der HARD_CLAMP-Zeile — dieselbe
  Quelle, aus der Zimmerliste und Zonenkarte ihren Zonenwert nehmen. Drei
  Ansichten, eine Quelle (Paragraph 5.53).
* ``geraet_setpoint`` ist der gemeldete Wert, **wenn er abweicht**. Im
  Normalfall ist die Reihe leer und das Diagramm sieht aus wie vorher;
  sie erscheint genau dann, wenn das Geraet nicht folgt. Das ist der
  Zweck von AE-74, nur als Abweichung statt als Sollwert.

Der Sonderfall fuer Zonen ohne Stellglied ist damit **weg**: die Regel
deckt ihn ab. Ein eingefrorener Geraetewert weicht ab und liegt in seiner
eigenen Reihe, wo er niemanden mehr in die Irre fuehrt.

Laeuft die Engine in einem Eimer nicht, bleibt der Sollwert ``None`` und
das Diagramm hat dort eine **Luecke**. Das ist die richtige Antwort und
nicht der Geraetewert: eine Luecke sagt „dazu wissen wir nichts", der
Geraetewert saehe wie eine Aussage aus.

**Kein Lifecycle-Filter, und das ist Absicht.** §5.58 verlangt
``retired_at IS NULL`` fuer jede Abfrage, die Geraete an Engine, Dispatch
oder Alarme weitergibt — hier geht nichts weiter, hier wird Vergangenheit
gezeigt. ``retire_device`` behaelt ``heating_zone_id`` ausdruecklich als
"Historie-Anker fuer sensor_reading" (AE-57), ein Filter wuerde also genau
die Zeilen wegwerfen, fuer die der Anker gedacht ist.

**Die Grenze, die das kostet:** ``replace_device`` setzt beim Getauschten
``heating_zone_id = None``. Die Messwerte des alten Kopfes sind damit nicht
mehr ueber die Zone erreichbar — nach einem Tausch beginnt der Verlauf des
Zimmers praktisch beim neuen Geraet. Die Zeilen sind nicht gelöscht, nur
nicht mehr zugeordnet. Festgehalten in RUNBOOK §10x; wer das aendern will,
braucht eine Zuordnung mit Gueltigkeitszeitraum und nicht einen Filter.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, Interval, cast, column, func, literal, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import EventLogLayer, HeatingZoneKind
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.rules.config_resolve import (
    lade_rule_configs,
    lade_zeitzone,
    resolve_rule_field,
)

# Fenster und Eimer je Bereich. Die Punktzahl je Zone steht daneben, weil
# sie die eigentliche Zusage ist: 144 bzw. 168 Punkte sind eine Linie, die
# ein Mensch lesen kann.
Bereich = Literal["24h", "7d"]

BEREICHE: dict[Bereich, tuple[timedelta, int]] = {
    "24h": (timedelta(hours=24), 10),  # 144 Punkte
    "7d": (timedelta(days=7), 60),  # 168 Punkte
}


@dataclass(frozen=True, slots=True)
class NachtBand:
    """Eine Absenkungs-Phase als UTC-Zeitspanne, zugeschnitten auf das Fenster."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class VerlaufPunkt:
    """Ein Eimer einer Zone."""

    t: datetime
    temperature: Decimal | None
    #: Der Sollwert, der **gilt** — der der Engine fuer diese Zone.
    setpoint: Decimal | None
    #: Was das Geraet meldet, **wenn es abweicht**, sonst ``None``.
    #:
    #: Zwei Werte und nicht einer, weil die Frage zwei ist: „worauf soll
    #: es stehen" und „worauf steht es". Bis zum 31.10.2026 trug
    #: ``setpoint`` den Geraetewert und beantwortete damit die zweite,
    #: waehrend die Beschriftung die erste versprach.
    geraet_setpoint: Decimal | None = None


@dataclass(frozen=True, slots=True)
class VerlaufZone:
    """Eine Zone mit ihrer Reihe. Leere Reihe heisst: Zone existiert,
    hat aber im Fenster nichts gemeldet."""

    zone_id: int
    name: str
    kind: HeatingZoneKind
    points: list[VerlaufPunkt]


@dataclass(frozen=True, slots=True)
class Verlauf:
    """Alles, was die Oberflaeche fuer ein Diagramm braucht — ohne dass sie
    etwas nachrechnet, das der Server schon weiss."""

    room_id: int
    bereich: Bereich
    bucket_minutes: int
    von: datetime
    bis: datetime
    timezone: str
    night_start: time | None
    night_end: time | None
    night_bands: list[NachtBand]
    zones: list[VerlaufZone]


def nacht_baender(
    *,
    von: datetime,
    bis: datetime,
    tz_name: str,
    night_start: time | None,
    night_end: time | None,
) -> list[NachtBand]:
    """Die Absenkungs-Phasen im Fenster, als UTC-Zeitspannen.

    **Warum das hier gerechnet wird und nicht im Browser.** Das
    Nachtfenster ist in **Ortszeit** konfiguriert, das Diagramm zeichnet auf
    einer UTC-Achse, und zwischen beidem liegt die Sommerzeit. Dieselbe
    Umrechnung macht die Engine (§5.65, AE-60) — mit ``zoneinfo``, das die
    Zeitumstellung kennt. Im Browser muesste man sie aus
    ``Intl.DateTimeFormat`` zurueckrechnen, und zwar ohne Testlauf: das
    Frontend hat keinen Unit-Test-Rahmen, nur Playwright. Eine
    Zeitzonen-Rechnung ohne Test ist genau die Klasse, die §5.79 teuer
    gemacht hat.

    Gelaufen wird ueber die lokalen Kalendertage, **einen Tag vor dem
    Fenster beginnend**: ein Band, das am Vortag um 22:00 anfaengt, reicht
    in das Fenster hinein und wuerde sonst fehlen.

    ``night_start > night_end`` ist der Normalfall (22:00 bis 06:00) und
    heisst: das Band endet am Folgetag.

    **Die Grenze, die bleibt:** in der doppelt vorhandenen Stunde der
    Rueckstellung (Ende Oktober) nimmt ``datetime.combine`` die erste
    Auslegung (``fold=0``). Das Band kann dort um eine Stunde daneben
    liegen — einmal im Jahr, in einer Stunde, in der niemand auf ein
    Diagramm sieht. Die Engine hat dieselbe Eigenschaft; sie hier anders
    aufzuloesen hiesse, zwei Wahrheiten zu bauen.
    """
    if night_start is None or night_end is None:
        return []
    tz = ZoneInfo(tz_name)
    erster: date = von.astimezone(tz).date() - timedelta(days=1)
    letzter: date = bis.astimezone(tz).date()

    baender: list[NachtBand] = []
    tag = erster
    while tag <= letzter:
        start_lokal = datetime.combine(tag, night_start, tzinfo=tz)
        ende_tag = tag if night_end > night_start else tag + timedelta(days=1)
        ende_lokal = datetime.combine(ende_tag, night_end, tzinfo=tz)
        # Auf das Fenster zuschneiden; was danach leer ist, war ausserhalb.
        a = max(start_lokal.astimezone(UTC), von)
        b = min(ende_lokal.astimezone(UTC), bis)
        if a < b:
            baender.append(NachtBand(start=a, end=b))
        tag += timedelta(days=1)
    return baender


async def _engine_sollwerte(
    session: AsyncSession,
    *,
    room_id: int,
    minuten: int,
    von: datetime,
    bis: datetime,
) -> dict[datetime, Decimal | None]:
    """Der HARD_CLAMP-Sollwert des **Zimmers**, in denselben Eimern.

    Quelle ist ``event_log.setpoint_out`` der Schicht ``HARD_CLAMP`` —
    derselbe Wert, den die Zonenkarte zeigt
    (``latest_hard_clamp_setpoint_per_room``). Zwei Wege zur selben
    Aussage waeren zwei Wahrheiten; der Verlauf nimmt deshalb den
    gleichen.

    ``max`` je Eimer, wie beim Geraete-Sollwert: innerhalb von zehn
    Minuten kann die Engine mehrfach gelaufen sein, und der zuletzt
    gueltige Wert ist der interessante. Dass ``max`` nicht „der letzte"
    ist, faellt nur auf, wenn der Sollwert innerhalb eines Eimers
    **sinkt** — dann zeigt das Diagramm zehn Minuten lang den hoeheren.
    Dieselbe Eigenschaft hat die Geraete-Reihe seit Sprint 21, und sie
    hier anders aufzuloesen hiesse, zwei Rechnungen zu haben.

    Seit dem 31.10.2026 ist das der **Rueckfall**: gezeigt wird der
    Sollwert je Zone (:func:`_engine_sollwerte_je_zone`), und dieser
    Zimmerwert greift nur, wo es dort keinen Eintrag gibt.
    """
    eimer_log = func.time_bucket(
        cast(literal(f"{minuten} minutes"), Interval), EventLog.time
    ).label("eimer")
    stmt = (
        select(eimer_log, func.max(EventLog.setpoint_out).label("sollwert"))
        .where(EventLog.room_id == room_id)
        .where(EventLog.layer == EventLogLayer.HARD_CLAMP)
        .where(EventLog.time >= von)
        .where(EventLog.time < bis)
        .group_by(eimer_log)
    )
    return {reihe.eimer: reihe.sollwert for reihe in (await session.execute(stmt)).all()}


async def _engine_sollwerte_je_zone(
    session: AsyncSession,
    *,
    room_id: int,
    minuten: int,
    von: datetime,
    bis: datetime,
) -> dict[tuple[datetime, int], int]:
    """Der Engine-Sollwert **je Zone** und Eimer. ``{(eimer, zone_id): wert}``.

    Quelle ist ``details['downlink_zone_status']`` der HARD_CLAMP-Zeile —
    dieselbe Stelle, aus der Zimmerliste und Zonenkarte ihren Zonenwert
    nehmen (``event_log.latest_hard_clamp_zone_setpoints``). Drei Ansichten,
    eine Quelle.

    **Ausgepackt wird in SQL** und nicht in Python, anders als beim
    Lesehelfer fuer den jeweils juengsten Wert. Der Unterschied ist die
    Menge: dort ist es **eine** Zeile je Zimmer, hier sind es im
    Sieben-Tage-Fenster ueber zehntausend, und die nach Python zu holen,
    um sie dort in Eimer zu sortieren, waere die Arbeit, fuer die es
    ``time_bucket`` gibt.

    ``max`` je Eimer und Zone, aus demselben Grund wie beim Zimmerwert.
    """
    # ``column("value", JSONB)`` und nicht nur ``"value"``: ohne den Typ
    # ist die Spalte fuer SQLAlchemy ``NullType``, und ein ``[...]``-Zugriff
    # darauf scheitert mit „Operator 'getitem' is not supported".
    zonen = func.jsonb_array_elements(EventLog.details["downlink_zone_status"]).table_valued(
        column("value", JSONB)
    )
    eimer_log = func.time_bucket(
        cast(literal(f"{minuten} minutes"), Interval), EventLog.time
    ).label("eimer")
    zone_id = zonen.c.value["zone_id"].astext.cast(Integer).label("zone_id")
    sollwert = func.max(zonen.c.value["setpoint_c"].astext.cast(Integer)).label("sollwert")
    stmt = (
        select(eimer_log, zone_id, sollwert)
        .select_from(EventLog)
        .join(zonen, true())
        .where(EventLog.room_id == room_id)
        .where(EventLog.layer == EventLogLayer.HARD_CLAMP)
        .where(EventLog.time >= von)
        .where(EventLog.time < bis)
        .group_by(eimer_log, zone_id)
    )
    return {
        (reihe.eimer, reihe.zone_id): reihe.sollwert
        for reihe in (await session.execute(stmt)).all()
        if reihe.zone_id is not None and reihe.sollwert is not None
    }


async def lade_verlauf(
    session: AsyncSession,
    *,
    room: Room,
    bereich: Bereich,
    jetzt: datetime | None = None,
) -> Verlauf:
    """Liest den Verlauf eines Zimmers.

    ``jetzt`` ist ein Argument und kein ``datetime.now()`` im Rumpf: so
    laesst sich der Beleg aus einem **festen** Fenster pruefen, statt aus
    einem, das jeden Tag weiterwandert. Genau daran ist die urspruengliche
    Abnahme dieses Tasks gescheitert — sie nannte Belegungen vom 05.10., und
    vier Tage spaeter lagen die nicht mehr in den letzten sieben Tagen.

    Das Fenster ist halboffen: ``>= von``, ``< bis``. Ein Messwert liegt
    damit in genau einem Eimer, auch an der Grenze.
    """
    fenster, minuten = BEREICHE[bereich]
    bis = jetzt if jetzt is not None else datetime.now(tz=UTC)
    von = bis - fenster

    # CAST('10 minutes' AS INTERVAL) statt eines eingesetzten Literals:
    # der Wert kommt aus BEREICHE, aber er geht trotzdem als Parameter in
    # die Abfrage und nicht in den Abfragetext.
    eimer = func.time_bucket(
        cast(literal(f"{minuten} minutes"), Interval), SensorReading.time
    ).label("eimer")

    stmt = (
        select(
            eimer,
            HeatingZone.id.label("zone_id"),
            func.round(func.avg(SensorReading.temperature), 2).label("temperatur"),
            func.max(SensorReading.setpoint).label("sollwert"),
        )
        .select_from(SensorReading)
        .join(Device, Device.id == SensorReading.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room.id)
        .where(SensorReading.time >= von)
        .where(SensorReading.time < bis)
        .group_by(eimer, HeatingZone.id)
        .order_by(eimer)
    )
    reihen = (await session.execute(stmt)).all()

    # **Der Sollwert ist der der Engine, der Geraetewert steht daneben**
    # (Befund des Betreibers, 31.10.2026 — Begruendung im Kopf).
    #
    # Hier stand bis dahin: Geraetewert als Sollwert, mit einem Sonderfall
    # fuer Zonen ohne Stellglied. Der Sonderfall ist weg, weil die Regel
    # ihn mit abdeckt — und der Geraetewert ist nicht verloren, er hat
    # jetzt seine eigene Reihe.
    engine_soll_zone = await _engine_sollwerte_je_zone(
        session, room_id=room.id, minuten=minuten, von=von, bis=bis
    )
    engine_soll_raum = await _engine_sollwerte(
        session, room_id=room.id, minuten=minuten, von=von, bis=bis
    )

    punkte_je_zone: dict[int, list[VerlaufPunkt]] = {}
    for reihe in reihen:
        # Reihenfolge der Quellen: Zone, dann Zimmer. Beides fehlt, wenn
        # die Engine in diesem Eimer nicht gelaufen ist — dann bleibt der
        # Sollwert ``None``, und das Diagramm hat dort eine Luecke.
        #
        # **Die Luecke ist die richtige Antwort**, nicht der Geraetewert.
        # Ein Rueckfall auf ihn waere genau der Befund: er sieht aus wie
        # ein Sollwert, ist aber nur der Wert, den das Geraet gerade
        # haelt — nach einer abgewiesenen Drehung also der des Gasts.
        zonen_wert = engine_soll_zone.get((reihe.eimer, reihe.zone_id))
        sollwert = (
            Decimal(zonen_wert) if zonen_wert is not None else engine_soll_raum.get(reihe.eimer)
        )
        # Der gemeldete Wert des Geraets, aber **nur wenn er abweicht**.
        #
        # Die Reihe hat damit im Normalfall keine Punkte und das Diagramm
        # sieht aus wie vorher: Ist und Soll, zwei Linien je Zone. Sie
        # erscheint genau dann, wenn das Geraet nicht auf dem Sollwert
        # steht — und das ist der Zweck, fuer den Sprint 21 A1 den
        # Geraetewert ueberhaupt gezeigt hat („ein nicht angekommener
        # Downlink soll sichtbar sein"). Nur zeigt sie jetzt die
        # **Abweichung** statt sie als Sollwert auszugeben.
        geraet = reihe.sollwert
        weicht_ab = geraet is not None and (sollwert is None or geraet != sollwert)
        punkte_je_zone.setdefault(reihe.zone_id, []).append(
            VerlaufPunkt(
                t=reihe.eimer,
                temperature=reihe.temperatur,
                setpoint=sollwert,
                geraet_setpoint=geraet if weicht_ab else None,
            )
        )

    # Alle Zonen des Zimmers, auch die stummen — und in stabiler
    # Reihenfolge, damit die Farben im Diagramm zwischen zwei Aufrufen
    # nicht wechseln.
    zonen_stmt = select(HeatingZone).where(HeatingZone.room_id == room.id).order_by(HeatingZone.id)
    zonen = list((await session.execute(zonen_stmt)).scalars().all())

    rule_configs = await lade_rule_configs(session, room_id=room.id, room_type_id=room.room_type_id)
    night_start = resolve_rule_field(rule_configs, "night_start")
    night_end = resolve_rule_field(rule_configs, "night_end")
    # Nur ein **vollstaendiges** Fenster ist ein Fenster. Eine halbe
    # Konfiguration (nur Beginn gesetzt) zeichnet sonst ein Band ohne Ende,
    # und die Engine wuerde daraus ebenfalls nichts machen.
    if night_start is None or night_end is None:
        night_start = night_end = None

    tz_name = await lade_zeitzone(session)

    return Verlauf(
        room_id=room.id,
        bereich=bereich,
        bucket_minutes=minuten,
        von=von,
        bis=bis,
        timezone=tz_name,
        night_start=night_start,
        night_end=night_end,
        night_bands=nacht_baender(
            von=von,
            bis=bis,
            tz_name=tz_name,
            night_start=night_start,
            night_end=night_end,
        ),
        zones=[
            VerlaufZone(
                zone_id=z.id,
                name=z.name,
                kind=z.kind,
                points=punkte_je_zone.get(z.id, []),
            )
            for z in zonen
        ],
    )
