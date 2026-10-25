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
* **Sollwert: Maximum** der gemeldeten Werte. Ein Sprung soll sichtbar
  sein, sobald er an **einem** Geraet ankommt. Das Mittel wuerde ihn
  verschleifen, solange ein zweites Geraet den Downlink noch nicht abgeholt
  hat — ein Vicki empfaengt nur im Fenster nach einem eigenen Uplink
  (§5.71), zwei Geraete einer Zone holen also nicht gleichzeitig ab.

**Der Sollwert kommt vom Geraet**, aus ``sensor_reading.setpoint``, nicht
aus ``control_command``. Dieselbe Entscheidung wie bei Regel 3c (AE-74):
gezeigt wird, was am Heizkoerper gilt, nicht was die Engine wollte. Ein
nicht angekommener Downlink ist damit im Diagramm **sichtbar** statt
geglaettet, und genau dafuer sieht man sich einen Verlauf an.

**Mit einer Ausnahme, und die ist ein Befund (Betreiber, 25.10.2026).**
Im Zimmer „Bar" zeigte die Zone „Barbereich (Soll)" durchgehend
**10 °C**, waehrend die Engine 21 bzw. 19 rechnete. Der Wert war echt: er
stand im Geraet, aus der Zeit, in der die Geraete-Sicherheit Frostschutz
erzwungen hat. Nur sagt er nichts mehr — eine Vicki mit der Rolle „nur
messen" bekommt **keine Sollwerte** (S7), ihr gespeicherter Wert friert
in dem Moment ein, in dem die Rolle gesetzt wird, und bleibt es.

Der Satz „gezeigt wird, was am Heizkoerper gilt" setzt voraus, dass das
Geraet den Heizkoerper stellt. Bei einem Fuehler ist das nicht so: er
stellt nichts, und sein Sollwert ist kein Zustand der Zone, sondern ein
Ueberrest. Fuer Zonen **ohne Stellglied** kommt der Sollwert deshalb aus
dem ``event_log`` — derselbe HARD_CLAMP-Wert, den die Zonenkarte zeigt.
So widerspricht der Verlauf nicht mehr der Karte darueber.

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

from sqlalchemy import Interval, cast, func, literal, select
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
from heizung.services.zone_aggregates import geraete_luecke_per_zone

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
    setpoint: Decimal | None


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
    """Der HARD_CLAMP-Sollwert des Zimmers, in denselben Eimern.

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

    # Sprint 24e (P3): welche Zonen haben kein Stellglied? Fuer die ist der
    # Sollwert des Geraets ein Ueberrest und nicht der Zustand der Zone
    # (Begruendung im Kopf). Eine Abfrage fuer alle Zonen des Zimmers.
    zone_ids = sorted({reihe.zone_id for reihe in reihen})
    luecken = await geraete_luecke_per_zone(session, zone_ids)
    nur_fuehler = {
        zid for zid, luecke in luecken.items() if luecke in {"kein_stellglied", "beides"}
    }
    engine_soll = (
        await _engine_sollwerte(session, room_id=room.id, minuten=minuten, von=von, bis=bis)
        if nur_fuehler
        else {}
    )

    punkte_je_zone: dict[int, list[VerlaufPunkt]] = {}
    for reihe in reihen:
        # ``None`` bleibt ``None``: gibt es fuer den Eimer keinen
        # Engine-Eintrag, wird nicht der Geraetewert eingesetzt. Ein
        # Rueckfall auf den eingefrorenen Wert waere genau der Befund, den
        # diese Aenderung behebt — nur seltener und damit schwerer zu
        # sehen.
        sollwert = engine_soll.get(reihe.eimer) if reihe.zone_id in nur_fuehler else reihe.sollwert
        punkte_je_zone.setdefault(reihe.zone_id, []).append(
            VerlaufPunkt(
                t=reihe.eimer,
                temperature=reihe.temperatur,
                setpoint=sollwert,
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
