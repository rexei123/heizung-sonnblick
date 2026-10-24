"""Sprint 14e FU-1 — Batch-Helper fuer Zone-Aggregat-Ist-Temperatur.

Liefert pro ``heating_zone_id`` den arithmetischen Mittelwert ueber die
juengsten Readings der **healthy + aktiven (``retired_at IS NULL``)** Vickis
einer Zone (AE-51 §4.1, §5.58). Reine Read-Aggregation auf vorhandenen
Tabellen — keine Schreib-Pfade, keine Engine-Kopplung.

Pattern ist parallel zu ``services.dashboard_aggregates._collect_zone_aggregates``
(Sprint 14c), aber per-Zone-ID-Filter statt Hotel-weitem Aggregat. Der reine
Mittelwert + Quantisierung lebt im Pure-Helper
``rules.aggregation.aggregate_zone_readings`` (eine Quelle der Wahrheit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ZonenIst:
    """Der Ist-Wert einer Zone **und** wann er gemessen wurde.

    Die Zeit kam mit Sprint 24d dazu, und zwar aus einem Befund: ein
    Mittelwert ohne Zeitstempel ist nicht von einem aktuellen zu
    unterscheiden, sobald die juengste Meldung keine Temperatur fuehrt.
    """

    mittel: Decimal | None
    stand: datetime | None


async def latest_mean_temp_per_zone(
    session: AsyncSession,
    zone_ids: Iterable[int],
) -> dict[int, ZonenIst]:
    """Pro Zone den juengsten Ist-Temp-Mittelwert ueber healthy + aktive Vickis.

    **Befund des Betreibers, 24.10.2026: die Zonenkarte zeigte „—".** Die
    Abfrage nahm die **juengste** Zeile je Geraet, ganz gleich ob sie eine
    Temperatur fuehrt. Eine Befehlsantwort fuehrt keine — und seit Sprint
    24c erzeugt das Setzen der Kindersicherung genau solche Frames
    (``0x14``). Ein Fuehler, der gerade erst geantwortet hat, sah damit
    aus wie einer, der nie gemessen hat.

    Der Filter steht deshalb in der **WHERE-Klausel** und nicht im
    Nachhinein: sonst kaeme fuer ein Geraet, dessen juengste Zeile das
    Feld nicht fuehrt, ``None`` heraus, obwohl die Zeile davor es fuehrt.
    Dieselbe Falle wie bei ``child_lock`` in 24c, zwei Tage spaeter und
    an einer anderen Spalte.

    ``ZonenIst.stand`` ist die **juengste** beitragende Messung der Zone
    (es koennen mehrere Geraete sein). Sie steht in der Oberflaeche neben
    dem Wert, damit ein alter Messwert als alter zu erkennen ist.

    Zwei Queries (R-D, kein N+1):

    1. ``Device`` mit ``retired_at IS NULL`` und ``heating_zone_id IN
       (zone_ids)`` — projiziert ``(id, heating_zone_id, health_state)``.
    2. Juengstes ``SensorReading`` pro Device via ``DISTINCT ON device_id``
       (Pattern aus ``dashboard_aggregates._collect_zone_aggregates``).

    Aggregation pro Zone delegiert an ``aggregate_zone_readings``
    (healthy-Filter + ``ROUND_HALF_EVEN`` auf 0.1 °C). Zonen ohne aktives
    Device tauchen mit ``None`` auf — Konsument muss alle erwarteten IDs
    selbst aus der Eingabe lesen, der Default-Pfad ist ``None``.
    """
    ids = list(zone_ids)
    if not ids:
        return {}

    leer = ZonenIst(mittel=None, stand=None)

    device_rows = (
        await session.execute(
            select(Device.id, Device.heating_zone_id, Device.health_state)
            .where(Device.retired_at.is_(None))
            .where(Device.heating_zone_id.in_(ids))
        )
    ).all()
    if not device_rows:
        return dict.fromkeys(ids, leer)

    device_ids = [row.id for row in device_rows]
    reading_rows = (
        await session.execute(
            select(
                SensorReading.device_id,
                SensorReading.temperature,
                SensorReading.open_window,
                SensorReading.time,
            )
            .where(SensorReading.device_id.in_(device_ids))
            .where(SensorReading.temperature.is_not(None))
            .order_by(SensorReading.device_id, SensorReading.time.desc())
            .distinct(SensorReading.device_id)
        )
    ).all()
    latest: dict[int, tuple[Decimal | None, bool | None, datetime]] = {
        row.device_id: (row.temperature, row.open_window, row.time) for row in reading_rows
    }

    by_zone: dict[int, list[ReadingForAggregate]] = {zone_id: [] for zone_id in ids}
    stand_je_zone: dict[int, datetime | None] = dict.fromkeys(ids)
    for device_id, zone_id, health_state in device_rows:
        temp, open_window, stand = latest.get(device_id, (None, None, None))
        by_zone[zone_id].append(
            ReadingForAggregate(
                temperature_c=temp,
                open_window=open_window,
                health_state=health_state,
            )
        )
        if stand is not None:
            bisher = stand_je_zone[zone_id]
            if bisher is None or stand > bisher:
                stand_je_zone[zone_id] = stand

    result: dict[int, ZonenIst] = {}
    for zone_id, readings in by_zone.items():
        mean_temp_c, _ = aggregate_zone_readings(readings)
        result[zone_id] = ZonenIst(
            mittel=mean_temp_c,
            # Kein Mittelwert, kein Stand: die Zeit eines Messwerts, der
            # nicht gezeigt wird, waere eine Angabe ohne Gegenstand.
            stand=stand_je_zone[zone_id] if mean_temp_c is not None else None,
        )
    return result


#: Was einer Zone fehlen kann. ``None`` heisst: nichts fehlt.
GeraeteLuecke = Literal["kein_fuehler", "kein_stellglied", "beides"]


async def geraete_luecke_per_zone(
    session: AsyncSession, zone_ids: Iterable[int]
) -> dict[int, GeraeteLuecke | None]:
    """Fehlt der Zone ein Fuehler, ein Stellglied, oder beides?

    **Befund des Betreibers, 24.10.2026.** Die Zone „Barbereich" trug das
    Kennzeichen „Kein Geraet", obwohl ihr die Fuehler-Vicki 027 zugeordnet
    ist. Das Kennzeichen hatte recht und sagte das Falsche: der Zone fehlt
    kein Geraet, ihr fehlt ein **Stellglied**. Ein Fuehler, der nur misst,
    kann nicht heizen — das ist seine Rolle und kein Mangel.

    „Kein Geraet" ist in dem Zustand der schlechteste von drei moeglichen
    Saetzen: er laesst den Betreiber nach einer fehlenden Zuordnung suchen,
    die er gerade gemacht hat. Die drei Faelle auseinanderzuhalten kostet
    eine Abfrage und spart den Gang zum Verteiler.

    Was als was zaehlt:

    * **Fuehler** ist jedes Thermostat — auch eines mit der Rolle „nur
      messen". Messen kann es.
    * **Stellglied** ist ein Relais oder ein Thermostat **ohne** diese
      Rolle. Ein Fuehler bekommt keine Sollwerte mehr (S7) und stellt
      nichts.

    Stillgelegte Geraete (``retired_at``) zaehlen nicht mit (§5.58) — ein
    Kopf im Lager heizt nicht.
    """
    ids = list(zone_ids)
    if not ids:
        return {}

    rows = (
        await session.execute(
            select(Device.heating_zone_id, Device.kind, Device.measure_only)
            .where(Device.retired_at.is_(None))
            .where(Device.heating_zone_id.in_(ids))
        )
    ).all()

    hat_fuehler: dict[int, bool] = dict.fromkeys(ids, False)
    hat_stellglied: dict[int, bool] = dict.fromkeys(ids, False)
    for zone_id, kind, measure_only in rows:
        if zone_id is None:
            continue
        if kind == DeviceKind.THERMOSTAT:
            hat_fuehler[zone_id] = True
            if not measure_only:
                hat_stellglied[zone_id] = True
        elif kind == DeviceKind.RELAY:
            hat_stellglied[zone_id] = True

    ergebnis: dict[int, GeraeteLuecke | None] = {}
    for zone_id in ids:
        if hat_fuehler[zone_id] and hat_stellglied[zone_id]:
            ergebnis[zone_id] = None
        elif hat_fuehler[zone_id]:
            ergebnis[zone_id] = "kein_stellglied"
        elif hat_stellglied[zone_id]:
            ergebnis[zone_id] = "kein_fuehler"
        else:
            ergebnis[zone_id] = "beides"
    return ergebnis
