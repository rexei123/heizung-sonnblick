"""Der Sollwert **je Zone** — eine Quelle für drei Ansichten (31.10.2026).

**Zwei Befunde des Betreibers aus dem Rad-Test von Zimmer 107**, und beide
haben dieselbe Wurzel:

* Die **Zimmerliste** zeigte „Soll 21,0 °C", während eine Übersteuerung auf
  23 °C für das Schlafzimmer galt und das Gerät 23 fuhr.
* Der **Verlauf** zeigte „Schlafzimmer (Soll): 25,0 °C" — den Wert, den der
  Gast gedreht hatte und den die Sperre abgewiesen hatte.

Die Wurzel: der Engine-Trace hielt nur den **Zimmer**-Sollwert fest
(``EventLog.setpoint_out`` der HARD_CLAMP-Zeile), plus den Bad-Wert als
Sonderfall. Eine **Zonen**-Übersteuerung stand nirgends. Also nahm die
Zimmerliste den Zimmerwert, die Zonenkarte ebenso, und der Verlauf nahm
stattdessen den Wert, den das **Gerät** meldete — jede Ansicht eine andere
Notlösung für dieselbe fehlende Zahl.

Seit dem 31.10.2026 schreibt der Dispatch den Zielwert je Zone in
``details['downlink_zone_status']``, und alle drei lesen ihn von dort. Es
ist derselbe Grund, aus dem ``bad_setpoint_c`` am 18.10. in den Trace kam,
nur eine Ebene allgemeiner — und deshalb **ersetzt** dieser Wert jenen
Sonderfall, statt neben ihm zu stehen (§5.53).

Diese Datei prüft den Lesepfad und den Verlauf. Die Zimmerliste steht in
``test_zimmerliste_ist_soll.py`` (dort liegt die Spalte), die Zonenkarte in
``test_badvorlage.py`` (dort lag der Sonderfall).

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).
§5.59: alle Zeitpunkte sind **absolute** Werte gegen ``FROZEN_NOW``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.api.v1.heating_zones import _build_zone_read
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services.event_log import latest_hard_clamp_zone_setpoints
from heizung.services.room_history import lade_verlauf
from tests.conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "sz-" + 4 hex = 7
PREFIX = "sz"
DEV_EUI_PATTERN = "5011ab%"

FROZEN_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

#: Der Fall von Zimmer 107: Zimmerwert 21, Zonen-Uebersteuerung 23,
#: gedrehter und abgewiesener Geraetewert 25.
ZIMMER, ZONE, GEDREHT = 21, 23, 25

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _zimmer(session: AsyncSession) -> tuple[Room, int, int]:
    """Belegtes Zimmer mit Schlafzimmer und Bad. ``(room, schlaf_id, bad_id)``."""
    marker = uuid.uuid4().hex[:4]
    typ = RoomType(
        name=f"{PREFIX}-dz-{marker}",
        default_t_occupied=Decimal("21.0"),
        default_t_vacant=Decimal("18.0"),
        default_t_night=Decimal("19.0"),
        min_temp_celsius=Decimal(15),
        max_temp_celsius=Decimal(25),
    )
    session.add(typ)
    await session.flush()
    room = Room(number=f"{PREFIX}-{marker}", room_type_id=typ.id, status=RoomStatus.OCCUPIED)
    session.add(room)
    await session.flush()
    session.add(
        Occupancy(
            room_id=room.id,
            check_in=FROZEN_NOW - timedelta(hours=20),
            check_out=FROZEN_NOW + timedelta(days=2),
            is_active=True,
        )
    )
    schlaf = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    bad = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BATHROOM, name="Bad")
    session.add_all([schlaf, bad])
    await session.flush()
    await session.commit()
    return room, schlaf.id, bad.id


async def _geraet_mit_messwert(
    session: AsyncSession,
    zone_id: int,
    *,
    meldet: int,
    wann: datetime | None = None,
) -> int:
    marker = uuid.uuid4().hex[:9]
    dev = Device(
        dev_eui=f"5011ab{marker[:10]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    session.add(
        SensorReading(
            time=wann or FROZEN_NOW - timedelta(minutes=5),
            device_id=dev.id,
            temperature=Decimal("22.5"),
            setpoint=Decimal(meldet),
        )
    )
    await session.commit()
    return dev.id


async def _hard_clamp(
    session: AsyncSession,
    room_id: int,
    *,
    zimmerwert: int,
    zonen: dict[int, Any] | None = None,
    wann: datetime | None = None,
) -> None:
    """Eine HARD_CLAMP-Zeile. ``zonen=None`` laesst den Zonen-Bericht weg."""
    details: dict[str, Any] = {"detail": "test"}
    if zonen is not None:
        details["downlink_zone_status"] = [
            {"zone_id": zid, "setpoint_c": wert, "count_sent": 1} for zid, wert in zonen.items()
        ]
    session.add(
        EventLog(
            time=wann or FROZEN_NOW - timedelta(minutes=1),
            room_id=room_id,
            evaluation_id=uuid.uuid4(),
            layer=EventLogLayer.HARD_CLAMP,
            setpoint_in=Decimal(zimmerwert),
            setpoint_out=Decimal(zimmerwert),
            reason=CommandReason.OCCUPIED_SETPOINT,
            details=details,
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# 1. Der Lesehelfer
# ---------------------------------------------------------------------------


async def test_helfer_liest_die_zonen_aus_der_juengsten_zeile(db_session: AsyncSession) -> None:
    """``{room_id: {zone_id: wert}}`` aus ``downlink_zone_status``."""
    room, schlaf, bad = await _zimmer(db_session)
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER, zonen={schlaf: ZONE, bad: 22})

    ergebnis = await latest_hard_clamp_zone_setpoints(db_session, [room.id])

    assert ergebnis == {room.id: {schlaf: ZONE, bad: 22}}


async def test_zeile_ohne_zonen_bericht_liefert_nichts(db_session: AsyncSession) -> None:
    """Eine Zeile aus der Zeit davor ergibt **keinen** Eintrag.

    Wichtig, dass hier nichts statt einer Null kommt: der Aufrufer
    unterscheidet „steht nicht da" (dann gilt der Zimmerwert) von einem
    Wert. Eine Null waere Frostschutz.
    """
    room, _, _ = await _zimmer(db_session)
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER)

    assert await latest_hard_clamp_zone_setpoints(db_session, [room.id]) == {}


async def test_wahrheitswert_wird_nicht_als_sollwert_gelesen(db_session: AsyncSession) -> None:
    """``true`` im Feld ist **kein** Sollwert von 1.

    ``isinstance(True, int)`` ist in Python wahr, und ein JSON-``true``
    waere damit lautlos ein Sollwert — in einem belegten Zimmer also
    Frostschutz minus neun Grad. Dieselbe Falle steht in
    ``test_geraetegrenzen_ende_zu_ende.py``; sie kostet eine Zeile und
    faellt sonst niemandem auf.
    """
    room, schlaf, _ = await _zimmer(db_session)
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER, zonen={schlaf: True})

    assert await latest_hard_clamp_zone_setpoints(db_session, [room.id]) == {}


async def test_alte_zeile_zaehlt_nicht(db_session: AsyncSession) -> None:
    """Dasselbe Frischefenster wie der Zimmerwert: eine Stunde.

    Ohne den Filter laesst ein totes Zimmer einen Zonenwert stehen, und
    die Liste zeigte ihn als heutigen Soll.
    """
    room, schlaf, _ = await _zimmer(db_session)
    await _hard_clamp(
        db_session,
        room.id,
        zimmerwert=ZIMMER,
        zonen={schlaf: ZONE},
        wann=datetime.now(tz=UTC) - timedelta(hours=2),
    )

    assert await latest_hard_clamp_zone_setpoints(db_session, [room.id]) == {}


async def test_leere_eingabe_fragt_nicht(db_session: AsyncSession) -> None:
    """Keine IDs, keine Abfrage — dieselbe Zusage wie bei den Nachbarn."""
    assert await latest_hard_clamp_zone_setpoints(db_session, []) == {}


# ---------------------------------------------------------------------------
# 2. Die Zonenkarte
# ---------------------------------------------------------------------------


async def test_zonenkarte_zeigt_den_wert_ihrer_uebersteuerung(db_session: AsyncSession) -> None:
    """**Der Befund an der Zonenkarte.** Karte zeigte 21 neben ihrer eigenen 23.

    Die Karte nennt die aktive Uebersteuerung seit Sprint 14d — und
    darueber stand der Zimmerwert als „Soll". Zwei Zahlen auf derselben
    Karte, die sich widersprachen.
    """
    room, schlaf, bad = await _zimmer(db_session)
    db_session.add(
        ManualOverride(
            room_id=room.id,
            heating_zone_id=schlaf,
            setpoint=Decimal(ZONE),
            source=OverrideSource.FRONTEND_CHECKOUT,
            expires_at=FROZEN_NOW + timedelta(days=2),
        )
    )
    await db_session.commit()
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER, zonen={schlaf: ZONE, bad: ZIMMER})

    schlaf_zone = await db_session.get(HeatingZone, schlaf)
    bad_zone = await db_session.get(HeatingZone, bad)
    assert schlaf_zone is not None and bad_zone is not None

    schlaf_read = await _build_zone_read(db_session, schlaf_zone)
    bad_read = await _build_zone_read(db_session, bad_zone)

    assert schlaf_read.engine_setpoint_c == Decimal(ZONE)
    assert bad_read.engine_setpoint_c == Decimal(ZIMMER), (
        "ohne eigene Uebersteuerung der Zimmerwert"
    )


# ---------------------------------------------------------------------------
# 3. Der Verlauf
# ---------------------------------------------------------------------------


async def test_verlauf_zeigt_den_engine_soll_und_die_abweichung_daneben(
    db_session: AsyncSession,
) -> None:
    """**Der Befund im Verlauf, als Test.** Soll 23, Gerät meldet 25.

    Genau die Lage von Zimmer 107: die Übersteuerung sagt 23, der Gast hat
    auf 25 gedreht, die Sperre hat die Drehung abgewiesen — und das Gerät
    hält 25. Vorher stand die 25 unter der Beschriftung „Soll".

    Jetzt stehen beide da, getrennt: ``setpoint`` ist 23 und
    ``geraet_setpoint`` ist 25. Das ist der Zweck von AE-74 („ein nicht
    angekommener Downlink soll sichtbar sein"), nur zeigt die Reihe die
    **Abweichung** statt sie als Sollwert auszugeben.
    """
    room, schlaf, _ = await _zimmer(db_session)
    await _geraet_mit_messwert(db_session, schlaf, meldet=GEDREHT)
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER, zonen={schlaf: ZONE})

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=FROZEN_NOW)

    zone = next(z for z in verlauf.zones if z.zone_id == schlaf)
    assert zone.points, "ein Messwert, ein Punkt"
    assert {p.setpoint for p in zone.points} == {Decimal(ZONE)}, (
        "der Soll der Zone, nicht der 21 des Zimmers und nicht die gedrehte 25"
    )
    assert {p.geraet_setpoint for p in zone.points} == {Decimal(GEDREHT)}


async def test_ohne_abweichung_bleibt_die_geraete_reihe_leer(db_session: AsyncSession) -> None:
    """**Die Gegenprobe, und sie ist die wichtigere.**

    Im Normalfall steht das Gerät auf dem Soll, und dann darf die dritte
    Linie nicht erscheinen. Fällt dieser Test, hat jedes Zimmer dauerhaft
    drei Linien je Zone statt zwei — aus einer Information über den
    Ausnahmefall wäre Rauschen im Regelfall geworden.
    """
    room, schlaf, _ = await _zimmer(db_session)
    await _geraet_mit_messwert(db_session, schlaf, meldet=ZONE)
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER, zonen={schlaf: ZONE})

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=FROZEN_NOW)

    zone = next(z for z in verlauf.zones if z.zone_id == schlaf)
    assert {p.setpoint for p in zone.points} == {Decimal(ZONE)}
    assert all(p.geraet_setpoint is None for p in zone.points), (
        "Gerät auf dem Soll — keine dritte Linie"
    )


async def test_verlauf_ohne_zonenwert_nimmt_den_zimmerwert(db_session: AsyncSession) -> None:
    """Der Rückfall gilt auch im Verlauf, Eimer für Eimer.

    Zeilen aus der Zeit vor dem 31.10.2026 tragen keinen Zonen-Bericht.
    Der Verlauf über sieben Tage läuft also noch tagelang teils auf den
    Zimmerwert — und das ist richtig, denn er war damals der einzige, den
    die Engine aufgeschrieben hat.
    """
    room, schlaf, _ = await _zimmer(db_session)
    await _geraet_mit_messwert(db_session, schlaf, meldet=GEDREHT)
    await _hard_clamp(db_session, room.id, zimmerwert=ZIMMER)

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=FROZEN_NOW)

    zone = next(z for z in verlauf.zones if z.zone_id == schlaf)
    assert {p.setpoint for p in zone.points} == {Decimal(ZIMMER)}


async def test_zwei_zonen_bekommen_ihre_eigenen_sollwerte(db_session: AsyncSession) -> None:
    """Zwei Zonen, zwei Werte, eine Zeile.

    Das ist die Zusage, die den Bad-Sonderfall ersetzt: das Bad bekommt
    seinen Vorlage-Wert nicht mehr über einen eigenen Pfad, sondern weil
    es eine Zone ist wie jede andere.
    """
    room, schlaf, bad = await _zimmer(db_session)
    await _geraet_mit_messwert(db_session, schlaf, meldet=19)
    await _geraet_mit_messwert(db_session, bad, meldet=22)
    await _hard_clamp(db_session, room.id, zimmerwert=19, zonen={schlaf: 19, bad: 22})

    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=FROZEN_NOW)

    werte = {z.zone_id: {p.setpoint for p in z.points} for z in verlauf.zones if z.points}
    assert werte == {schlaf: {Decimal(19)}, bad: {Decimal(22)}}


# ---------------------------------------------------------------------------
# 4. Schreiber und Leser passen zusammen
# ---------------------------------------------------------------------------


async def test_was_der_dispatch_schreibt_liest_der_helfer(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Die Probe, die alle anderen hier nicht machen.**

    Jeder Test oben schreibt die ``HARD_CLAMP``-Zeile von Hand. Hiesse das
    Feld im Dispatch anders, waeren sie alle gruen und die Anzeige leer —
    genau der Fall aus Paragraph 5.55, ein gruener Lauf, der nichts
    geprueft hat. Die Mutationsprobe hat das zuerst gezeigt: ein
    entferntes ``setpoint_c`` im Dispatch liess sie unberuehrt.

    Dieser Test laesst den **echten** Dispatch laufen, legt dessen
    Zonen-Bericht in die ``details`` — so, wie ``_evaluate_room_async`` es
    tut — und liest ihn mit dem Helfer der Anzeige zurueck.

    Was dazwischen ungeprueft bleibt, ist die eine Zeile
    ``base_details["downlink_zone_status"] = per_zone_status``; sie ist
    aelter als dieser PR und von den Trace-Tests gedeckt.
    """
    from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone

    async def _nicht_senden(dev_eui: str, setpoint_c: int) -> str:
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _nicht_senden)

    room, schlaf, bad = await _zimmer(db_session)
    await _geraet_mit_messwert(db_session, schlaf, meldet=ZIMMER)
    await _geraet_mit_messwert(db_session, bad, meldet=ZIMMER)

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=ZIMMER,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        zone_overrides={schlaf: ZONE},
    )

    db_session.add(
        EventLog(
            time=datetime.now(tz=UTC) - timedelta(seconds=5),
            room_id=room.id,
            evaluation_id=uuid.uuid4(),
            layer=EventLogLayer.HARD_CLAMP,
            setpoint_in=Decimal(ZIMMER),
            setpoint_out=Decimal(ZIMMER),
            reason=CommandReason.OCCUPIED_SETPOINT,
            details={"detail": "test", "downlink_zone_status": pro_zone},
        )
    )
    await db_session.commit()

    gelesen = await latest_hard_clamp_zone_setpoints(db_session, [room.id])

    assert gelesen == {room.id: {schlaf: ZONE, bad: ZIMMER}}, (
        "der Dispatch schreibt und der Helfer liest denselben Schluessel"
    )
