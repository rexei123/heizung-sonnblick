"""Sprint 23 — welche Geraete Hardware-Befehle bekommen duerfen.

**Ergaenzung 2 des Auftrags verlangt diesen Test ausdruecklich:** Geraete
auf „nur messen" (die Vickis 027 und 056) und der Reserve-Pool (100) sind
von Rollouts ausgenommen, *mit Test*.

Der Anlass ist kein hypothetischer. Bis Sprint 23 T2 lautete die Auswahl
im Bulk-Skript „Thermostat mit Zone" — ein Fuehler auf „nur messen" haette
ein ``0x45`` bekommen, und mit T1 haette er ein ``0x08`` dazubekommen.

Geprueft wird auf **zwei Ebenen**, und das ist nicht doppelt:
``ausnahme_grund`` ist eine reine Funktion und beweist, dass die **Regel**
stimmt; der DB-Test am Ende beweist, dass die **Abfrage** sie anwendet.
Paragraph 5.83 — eine Zusicherung gilt nur auf der Ebene, auf der sie
geprueft wurde.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

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
from heizung.services.geraete_ziele import (
    GRUND_AUSGEMUSTERT,
    GRUND_KEIN_THERMOSTAT,
    GRUND_NUR_MESSEN,
    GRUND_OHNE_ZONE,
    Ausnahme,
    MehrdeutigeAuswahlError,
    Zielgeraet,
    ausnahme_grund,
    lade_ziele,
    nicht_gefunden,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - der Abfrage-Test braucht Test-DB"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Eine Sitzung gegen die Test-Datenbank.

    Eigene Huelle statt einer globalen: das Repo hat keine, und die
    bestehenden DB-Tests bauen sie je Modul.
    """
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
    finally:
        await engine.dispose()


def _geraet(
    *,
    measure_only: bool = False,
    zone_id: int | None = 7,
    retired: bool = False,
    kind: DeviceKind = DeviceKind.THERMOSTAT,
) -> Device:
    """Ein Geraete-Objekt ohne Datenbank — ``ausnahme_grund`` ist rein."""
    return Device(
        dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
        label="Pruefgeraet",
        kind=kind,
        measure_only=measure_only,
        heating_zone_id=zone_id,
        retired_at=datetime.now(tz=UTC) if retired else None,
    )


def test_nur_messen_ist_ausgenommen() -> None:
    """Vicki 027 und 056: Fuehler im Raum, bekommen keine Befehle (S7).

    Das ist der Fall, den Ergaenzung 2 ausdruecklich nennt. Ein 0x45 an
    ein solches Geraet waere nicht nur sinnlos — es widerspricht der
    Rolle, und die Rolle ist der Grund, warum das Drehrad dort gesperrt
    ist.
    """
    assert ausnahme_grund(_geraet(measure_only=True)) == GRUND_NUR_MESSEN


def test_reserve_pool_ist_ausgenommen() -> None:
    """Geraet 100 liegt ohne Zone im Lager."""
    assert ausnahme_grund(_geraet(zone_id=None)) == GRUND_OHNE_ZONE


def test_ausgemustertes_geraet_ist_ausgenommen() -> None:
    """Und zwar vor allen anderen Gruenden — es ist nicht mehr da."""
    assert ausnahme_grund(_geraet(retired=True)) == GRUND_AUSGEMUSTERT
    # Auch wenn es noch eine Zone traegt und nicht auf „nur messen" steht.
    assert ausnahme_grund(_geraet(retired=True, measure_only=True)) == GRUND_AUSGEMUSTERT


def test_relais_ist_ausgenommen() -> None:
    """Ein Relais misst nicht und hat kein Drehrad."""
    assert ausnahme_grund(_geraet(kind=DeviceKind.RELAY)) == GRUND_KEIN_THERMOSTAT


def test_montiertes_thermostat_ist_ein_ziel() -> None:
    assert ausnahme_grund(_geraet()) is None


def test_jeder_grund_hat_einen_test() -> None:
    """Spiegel-Test: eine neue Ausnahme ohne Test faellt hier auf.

    Ohne ihn waere die Ergaenzung-2-Zusicherung an den Fleiss des
    naechsten Durchgangs gebunden — und eine Zusicherung, die niemand
    prueft, ist eine Behauptung (§5.68).
    """
    geprueft = {
        GRUND_NUR_MESSEN,
        GRUND_OHNE_ZONE,
        GRUND_AUSGEMUSTERT,
        GRUND_KEIN_THERMOSTAT,
    }
    aus_modul = {
        wert
        for name, wert in vars(__import__("heizung.services.geraete_ziele", fromlist=["x"])).items()
        if name.startswith("GRUND_") and isinstance(wert, str)
    }
    assert aus_modul == geprueft, f"ungeprueft: {aus_modul - geprueft}"


def test_nicht_gefundene_bezeichnung_wird_gemeldet() -> None:
    """Ein Tippfehler darf nicht als „alles ausgenommen" durchgehen."""
    ziele = [
        Zielgeraet(
            device_id=1,
            dev_eui="deadbeef00000001",
            label="A",
            firmware_version="4.5",
            heating_zone_id=9,
            zone_name="Schlafzimmer",
            room_number="306",
        )
    ]
    ausnahmen = [Ausnahme(dev_eui="deadbeef00000002", label="B", grund=GRUND_NUR_MESSEN)]

    assert nicht_gefunden(["306 Schlafzimmer"], ziele, ausnahmen) == []
    assert nicht_gefunden(["B"], ziele, ausnahmen) == []
    assert nicht_gefunden(["305 Schlafzimmer"], ziele, ausnahmen) == ["305 Schlafzimmer"]


# ---------------------------------------------------------------------------
# Die Ausnahmen in der Abfrage, nicht nur in der reinen Funktion
# ---------------------------------------------------------------------------


async def test_lade_ziele_nimmt_nur_messen_und_pool_wirklich_aus(
    db_session: AsyncSession,
) -> None:
    """Ergaenzung 2, auf Abfrage-Ebene geprueft.

    ``ausnahme_grund`` ist eine reine Funktion und beweist, dass die
    **Regel** stimmt. Dass die **Abfrage** sie anwendet, ist eine andere
    Aussage — und genau die Luecke, durch die das Bulk-Skript jahrelang
    Fuehler mitgenommen hat. §5.83: eine Zusicherung gilt nur auf der
    Ebene, auf der sie geprueft wurde.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"t2-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"t2-{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    db_session.add(zone)
    await db_session.flush()

    montiert = Device(
        dev_eui=f"aa00{suffix}aa00",
        label=f"montiert-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        measure_only=False,
        firmware_version="4.5",
    )
    fuehler = Device(
        dev_eui=f"bb00{suffix}bb00",
        label=f"nurmessen-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
        measure_only=True,
    )
    pool = Device(
        dev_eui=f"cc00{suffix}cc00",
        label=f"pool-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=None,
        measure_only=False,
    )
    db_session.add_all([montiert, fuehler, pool])
    await db_session.commit()

    try:
        ziele, ausnahmen = await lade_ziele(db_session)
        eigene_ziele = {z.dev_eui for z in ziele} & {
            montiert.dev_eui,
            fuehler.dev_eui,
            pool.dev_eui,
        }
        assert eigene_ziele == {montiert.dev_eui}

        gruende = {a.dev_eui: a.grund for a in ausnahmen}
        assert gruende.get(fuehler.dev_eui) == GRUND_NUR_MESSEN
        assert gruende.get(pool.dev_eui) == GRUND_OHNE_ZONE

        # Die Bezeichnung aus dem Testplan ("306 Schlafzimmer") muss als
        # Auswahl funktionieren — eine DevEUI tippt niemand ab.
        nur_dieses, _ = await lade_ziele(db_session, nur=[f"t2-{suffix} Schlafzimmer"])
        assert [z.dev_eui for z in nur_dieses] == [montiert.dev_eui]
        assert nur_dieses[0].bezeichnung == f"t2-{suffix} Schlafzimmer"
    finally:
        for d in (montiert, fuehler, pool):
            await db_session.execute(text("DELETE FROM device WHERE id = :i"), {"i": d.id})
        await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
        await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
        await db_session.commit()


# ---------------------------------------------------------------------------
# Abbruch bei zweideutigem ``--nur`` (Entscheidung des Betreibers, 01.11.2026)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_etikett_und_zimmernummer_zugleich_bricht_ab(db_session: AsyncSession) -> None:
    """``--nur "105"`` darf nicht lautlos ein Geraet zu viel treffen.

    **Der Anlass.** ``--nur`` waehlt nach DevEUI **oder** Etikett
    **oder** Zimmernummer **oder** „Zimmer Zone". Mit den
    Geraetenamen 105-109 ist ``105`` beides: Etikett eines Vickis und
    Nummer eines Testzimmers. Trifft beides, ist die Zahl der Ziele um
    eins zu hoch — und wer sie abzaehlt, sieht ein Geraet, das er
    vergessen zu haben glaubt.

    Geprueft wird hier der **scharfe** Fall: das gleichnamige Geraet
    haengt in einer Zone und ist damit ein Ziel.
    """
    suffix = uuid.uuid4().hex[:6]
    nummer = f"z{suffix}"  # spielt die Rolle der Zimmernummer „105"

    rt = RoomType(name=f"md-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    zimmer_a = Room(number=nummer, room_type_id=rt.id)
    zimmer_b = Room(number=f"and-{suffix}", room_type_id=rt.id)
    db_session.add_all([zimmer_a, zimmer_b])
    await db_session.flush()
    zone_a = HeatingZone(room_id=zimmer_a.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    zone_b = HeatingZone(room_id=zimmer_b.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    db_session.add_all([zone_a, zone_b])
    await db_session.flush()

    # Zwei Thermostate im Zimmer mit dieser Nummer …
    im_zimmer = [
        Device(
            dev_eui=f"ee0{i}{suffix}ee0{i}",
            label=f"imzimmer-{i}-{suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone_a.id,
        )
        for i in (1, 2)
    ]
    # … und ein Geraet, dessen **Etikett** dieselbe Zeichenfolge ist,
    # zugeordnet in einem anderen Zimmer.
    gleichnamig = Device(
        dev_eui=f"ff00{suffix}ff00",
        label=nummer,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_b.id,
    )
    db_session.add_all([*im_zimmer, gleichnamig])
    await db_session.commit()

    try:
        with pytest.raises(MehrdeutigeAuswahlError) as fehler:
            await lade_ziele(db_session, nur=[nummer])

        text_der_meldung = str(fehler.value)
        assert "Etikett" in text_der_meldung
        assert "Zimmernummer" in text_der_meldung
        # **Die Trefferliste gehoert in die Meldung** (Auftrag des
        # Betreibers): wer abbricht, muss sehen, welche Geraete gemeint
        # sein koennten — sonst ist der Abbruch eine Sackgasse.
        assert gleichnamig.dev_eui in text_der_meldung
        for d in im_zimmer:
            assert d.dev_eui in text_der_meldung
    finally:
        for d in (*im_zimmer, gleichnamig):
            await db_session.execute(text("DELETE FROM device WHERE id = :i"), {"i": d.id})
        for z in (zone_a, zone_b):
            await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": z.id})
        for r in (zimmer_a, zimmer_b):
            await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": r.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
        await db_session.commit()


@pytest.mark.asyncio
async def test_eine_zimmernummer_fuer_mehrere_thermostate_ist_eindeutig(
    db_session: AsyncSession,
) -> None:
    """Mehrere Treffer auf **demselben** Weg sind kein Fehler.

    Eine Zimmernummer trifft alle Thermostate ihres Zimmers — genau
    dafuer ist sie da. Ein Abbruch hier waere die naheliegende und
    falsche Fassung derselben Regel, und sie haette §10ar unbenutzbar
    gemacht: dort gehen drei ``0x07`` an **ein** Zimmer.
    """
    suffix = uuid.uuid4().hex[:6]
    rt = RoomType(name=f"me-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=f"m{suffix}", room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    db_session.add(zone)
    await db_session.flush()
    geraete = [
        Device(
            dev_eui=f"ab0{i}{suffix}ab0{i}",
            label=f"drei-{i}-{suffix}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
        )
        for i in (1, 2, 3)
    ]
    db_session.add_all(geraete)
    await db_session.commit()

    try:
        ziele, _ = await lade_ziele(db_session, nur=[room.number])
        assert {z.dev_eui for z in ziele} == {d.dev_eui for d in geraete}
    finally:
        for d in geraete:
            await db_session.execute(text("DELETE FROM device WHERE id = :i"), {"i": d.id})
        await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
        await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
        await db_session.commit()


@pytest.mark.asyncio
async def test_ein_pool_geraet_mit_demselben_namen_bricht_nicht_ab(
    db_session: AsyncSession,
) -> None:
    """Solange das gleichnamige Geraet im Lager liegt, laeuft alles weiter.

    **Das ist der Fall dieser Woche**, und er darf den T2-Lauf nicht
    aufhalten: die neuen Vickis heissen 105-109 und liegen ohne Zone im
    Reserve-Pool, waehrend ``--nur "105"`` das **Zimmer** 105 meint. Ein
    Pool-Geraet ist eine Ausnahme und bekommt keinen Befehl — ein
    Abbruch waere ein Abbruch ohne Gefahr.

    Scharf wird es erst bei der **Zuordnung**, und genau das prueft der
    Test darueber.
    """
    suffix = uuid.uuid4().hex[:6]
    nummer = f"p{suffix}"
    rt = RoomType(name=f"mp-{suffix}")
    db_session.add(rt)
    await db_session.flush()
    room = Room(number=nummer, room_type_id=rt.id)
    db_session.add(room)
    await db_session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    db_session.add(zone)
    await db_session.flush()
    im_zimmer = Device(
        dev_eui=f"cd00{suffix}cd00",
        label=f"imzimmer-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone.id,
    )
    im_pool = Device(
        dev_eui=f"de00{suffix}de00",
        label=nummer,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=None,
    )
    db_session.add_all([im_zimmer, im_pool])
    await db_session.commit()

    try:
        ziele, ausnahmen = await lade_ziele(db_session, nur=[nummer])
        assert [z.dev_eui for z in ziele] == [im_zimmer.dev_eui]
        # Das Pool-Geraet steht als Ausnahme **mit Grund** da und nicht
        # stillschweigend nicht da.
        assert {a.dev_eui: a.grund for a in ausnahmen}.get(im_pool.dev_eui) == GRUND_OHNE_ZONE
    finally:
        for d in (im_zimmer, im_pool):
            await db_session.execute(text("DELETE FROM device WHERE id = :i"), {"i": d.id})
        await db_session.execute(text("DELETE FROM heating_zone WHERE id = :i"), {"i": zone.id})
        await db_session.execute(text("DELETE FROM room WHERE id = :i"), {"i": room.id})
        await db_session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt.id})
        await db_session.commit()
