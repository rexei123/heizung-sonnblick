"""Sprint 23 T1 — die Temperaturgrenzen am Geraet.

Drei Ebenen, und die Erwartungswerte der ersten kommen aus der
**Hersteller-Doku**, nicht aus unserem eigenen Lauf (Paragraph 5.79):

1. **Die Bytes.** ``0x08`` und ``0x15``, mit den beiden Belegen der Doku
   (``0x081018`` = 16/24 °C, Antwort ``0x15051E`` = 5/30 °C) und den
   Werten des Hauses (Zimmer 15/25, Bad 18/25).
2. **Soll gegen Ist.** Woher die Soll-Grenzen kommen (Bad-Zonen folgen
   der Vorlage) und was aus einer fehlenden Antwort folgt.
3. **Der Abgleich.** Wann gesendet wird — und vor allem: wann **nicht**.
   Die vierte Pruefung des Pflicht-Stops lautet „keine zusaetzlichen
   Downlinks, wenn die Grenzen stimmen"; dieser Test ist ihre
   Entsprechung in der Suite.

**Die Verwechslungsgefahr, gegen die der erste Abschnitt steht:** der
Sollwert (``0x51``) wird mit zehn multipliziert, die Grenzen **nicht**.
Mit Faktor zehn waere aus 15/25 ein Wert von 150/250 geworden, und das
Geraet haette ihn abgeschnitten oder verworfen, ohne es zu sagen.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services.downlink_adapter import (
    VICKI_TEMP_RANGE_GET_COMMAND,
    VICKI_TEMP_RANGE_SET_COMMAND,
    DownlinkError,
    temp_range_bytes,
)
from heizung.services.geraetegrenzen import (
    Grenzbefund,
    Grenzen,
    ist_grenzen_je_geraet,
    muss_gesendet_werden,
    soll_grenzen_je_zone,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - die DB-Tests brauchen Test-DB"


# ---------------------------------------------------------------------------
# 1. Die Bytes
# ---------------------------------------------------------------------------


def test_beleg_der_hersteller_doku() -> None:
    """``0x081018`` = 16/24 °C — das Beispiel der Doku, woertlich.

    Quelle: docs.mclimate.eu, Vicki-Protokoll, „Limit target temperature
    range", abgerufen 21.10.2026. Dieser Test ist der Grund, warum die
    Grenzen **nicht** skaliert werden: 16 ist ``0x10``, nicht ``0xA0``.
    """
    assert temp_range_bytes(16, 24).hex() == "081018"


def test_werte_des_hauses() -> None:
    """Zimmer 15/25 und Bad 18/25, wie im Auftrag genannt."""
    assert temp_range_bytes(15, 25).hex() == "080f19"
    assert temp_range_bytes(18, 25).hex() == "081219"


def test_befehlscodes_stimmen() -> None:
    assert VICKI_TEMP_RANGE_SET_COMMAND == 0x08
    assert VICKI_TEMP_RANGE_GET_COMMAND == 0x15


def test_grenzen_ausserhalb_der_spanne_werden_abgewiesen() -> None:
    """Werk ist 5/30; darueber hinaus wird abgewiesen, nicht beschnitten.

    Wer 35 schickt, hat sich vertippt und soll es erfahren. Ein stilles
    Beschneiden waere ein Befehl, der etwas anderes tut als er sagt.
    """
    with pytest.raises(DownlinkError):
        temp_range_bytes(4, 25)
    with pytest.raises(DownlinkError):
        temp_range_bytes(15, 35)


def test_vertauschte_grenzen_werden_abgewiesen() -> None:
    with pytest.raises(DownlinkError):
        temp_range_bytes(25, 15)
    with pytest.raises(DownlinkError):
        temp_range_bytes(20, 20)


def test_keine_floats() -> None:
    """Ganze Grad, und der Typ sagt es.

    Ein ``15.5`` waere beim Byte-Bau stillschweigend zu 15 geworden — und
    damit haette die Oberflaeche eine Grenze gezeigt, die am Geraet
    anders gilt.
    """
    with pytest.raises(DownlinkError):
        temp_range_bytes(15.5, 25)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Der Abgleich — wann gesendet wird, und wann nicht
# ---------------------------------------------------------------------------


def test_ohne_antwort_wird_gesendet() -> None:
    """Ein Geraet, von dem wir nichts gehoert haben, steht womoeglich auf 5/30.

    Dann darf der Gast auf 30 drehen. Lieber ein Befehl zu viel als eine
    Grenze, die es nicht gibt.
    """
    assert muss_gesendet_werden(Grenzen(15, 25), None) is True


def test_bei_abweichung_wird_gesendet() -> None:
    befund = Grenzbefund(grenzen=Grenzen(5, 30), gemeldet_um=datetime.now(tz=UTC))
    assert muss_gesendet_werden(Grenzen(15, 25), befund) is True


def test_bei_uebereinstimmung_wird_nicht_gesendet() -> None:
    """Die vierte Pruefung des Pflicht-Stops, als Test.

    Der Abgleich darf nicht jede Viertelstunde funken, wenn die Grenzen
    stimmen — Batterie und Motor sind real (S4).
    """
    befund = Grenzbefund(grenzen=Grenzen(15, 25), gemeldet_um=datetime.now(tz=UTC))
    assert muss_gesendet_werden(Grenzen(15, 25), befund) is False


# ---------------------------------------------------------------------------
# 3. Soll und Ist aus der Datenbank
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
    finally:
        await engine.dispose()


async def test_soll_grenzen_kommen_aus_dem_raumtyp_und_bad_aus_der_vorlage(
    db_session: AsyncSession,
) -> None:
    """Dieselbe Rangfolge wie der Bad-Sollwert (18.10.2026).

    Ein Bad folgt der Vorlage, das Schlafzimmer dem Zimmertyp. Ohne diese
    Unterscheidung bekaeme ein Bad die Untergrenze des Zimmers (15) statt
    seiner eigenen (18) — und der Gast koennte es auf 15 drehen.

    Die Vorlage wird ueber den **Namen** des Raumtyps gefunden
    (``BAD_VORLAGE_ROOM_TYPE``, Vorgabe „Bad"); gibt es sie nicht,
    verhaelt sich alles wie vor dem 18.10. Dieser Test legt sie an und
    raeumt sie wieder ab — er darf nicht davon abhaengen, ob im Haus
    gerade eine existiert.
    """
    suffix = uuid.uuid4().hex[:8]
    vorlage = RoomType(name="Bad", min_temp_celsius=18, max_temp_celsius=25)
    vorhandene_vorlage = await db_session.scalar(
        text("SELECT id FROM room_type WHERE name = 'Bad' LIMIT 1")
    )
    if vorhandene_vorlage is None:
        db_session.add(vorlage)
        await db_session.flush()
        vorlage_id: int | None = vorlage.id
    else:
        vorlage_id = None  # nicht von uns, nicht abraeumen

    zimmertyp = RoomType(name=f"t1-{suffix}", min_temp_celsius=15, max_temp_celsius=25)
    db_session.add(zimmertyp)
    await db_session.flush()
    room = Room(number=f"t1-{suffix}", room_type_id=zimmertyp.id)
    db_session.add(room)
    await db_session.flush()
    schlaf = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    bad = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BATHROOM, name="Bad")
    db_session.add_all([schlaf, bad])
    await db_session.commit()

    try:
        soll = await soll_grenzen_je_zone(db_session, [schlaf.id, bad.id])
        assert soll[schlaf.id] == Grenzen(15, 25)
        assert soll[bad.id] == Grenzen(18, 25), "Bad-Zone folgt nicht der Vorlage"
    finally:
        for z in (schlaf, bad):
            await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": z.id})
        await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": zimmertyp.id})
        if vorlage_id is not None:
            await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": vorlage_id})
        await db_session.commit()


async def test_ist_grenzen_nehmen_die_juengste_zeile_die_die_felder_fuehrt(
    db_session: AsyncSession,
) -> None:
    """Die Regel, die bei ``child_lock`` schon einmal falsch war (24c).

    Nach der ``0x15``-Antwort kommen weitere Keepalives, und die fuehren
    die Grenzen **nicht**. Wer schlicht die juengste Zeile nimmt, sieht
    ``NULL`` und meldet „nicht bestaetigt" — obwohl die Antwort vorliegt.

    Geprueft wird deshalb mit einer Reihenfolge, die genau das abbildet:
    alte Antwort, neue Antwort, danach ein Keepalive ohne die Felder.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t1i-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"t1i-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    db_session.add(zone)
    await db_session.flush()
    geraet = Device(
        dev_eui=f"dd00{suffix}dd00",
        label=f"t1i-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    db_session.add(geraet)
    await db_session.flush()

    jetzt = datetime.now(tz=UTC)
    db_session.add_all(
        [
            # alte Antwort: Werkseinstellung
            SensorReading(
                device_id=geraet.id,
                time=jetzt - timedelta(hours=2),
                temp_range_min=5,
                temp_range_max=30,
            ),
            # neue Antwort: unsere Grenzen
            SensorReading(
                device_id=geraet.id,
                time=jetzt - timedelta(hours=1),
                temp_range_min=15,
                temp_range_max=25,
            ),
            # danach ein Keepalive, der die Felder nicht fuehrt
            SensorReading(
                device_id=geraet.id,
                time=jetzt,
                temperature=21,
                valve_position=40,
            ),
        ]
    )
    await db_session.commit()

    try:
        befunde = await ist_grenzen_je_geraet(db_session, [geraet.id])
        befund = befunde[geraet.id]
        assert befund is not None, "der Keepalive hat die Antwort verdeckt"
        assert befund.grenzen == Grenzen(15, 25)
        assert befund.gemeldet_um == jetzt - timedelta(hours=1)
    finally:
        await db_session.execute(
            text("DELETE FROM sensor_reading WHERE device_id = :i"), {"i": geraet.id}
        )
        await db_session.execute(text("DELETE FROM device WHERE id = :i"), {"i": geraet.id})
        await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
        await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
        await db_session.commit()


async def test_ohne_antwort_steht_none_und_der_schluessel_fehlt_nicht(
    db_session: AsyncSession,
) -> None:
    """Jede angefragte ID kommt im Ergebnis vor.

    Ein fehlender Schluessel waere fuer den Aufrufer nicht von „keine
    Antwort" zu unterscheiden, und dann muesste er raten — dieselbe Regel
    wie bei ``child_lock_verdicts`` und ``battery_verdicts``.
    """
    befunde = await ist_grenzen_je_geraet(db_session, [-1, -2])
    assert befunde == {-1: None, -2: None}
    assert await ist_grenzen_je_geraet(db_session, []) == {}
