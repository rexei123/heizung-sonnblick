"""Sprint 23 T4-A — die Gast-Sperre endet mit der Abreise.

Geprueft wird in drei Schichten, weil der Fehler in jeder einzelnen
anders aussieht:

1. **Der Loese-Dienst** (``services/gast_sperre``): greift er genau beim
   Uebergang OCCUPIED -> VACANT, und laesst er eine dauerhaft gesetzte
   Sperre stehen?
2. **Der Endpoint**: weist er die beiden unsinnigen Faelle ab, und
   vergleicht seine Idempotenz **beide** Felder?
3. **Die Kette**: loest ein echter Belegungs-Abgleich
   (``sync_room_status``) die Sperre wirklich? Ohne diese Stufe waere
   bewiesen, dass die Funktion funktioniert, und nicht, dass sie
   aufgerufen wird — der Unterschied, an dem Paragraph 5.55 haengt.

Pattern-Spiegel zu ``test_api_rooms.py`` (eigener ``setup_engine``,
``alembic upgrade head`` im Thread wegen des env.py-asyncio-Konflikts).
Suffixe kommen aus ``uuid4`` und nicht aus der Uhr — eine Tageszeit im
Namen hat Parallel-Lauf-Potenzial (Paragraph 5.59).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import OccupancySource, OverrideSource, RoomStatus
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import occupancy_service, override_service
from heizung.services.gast_sperre import (
    ACTION_GELOEST,
    VIA_UEBERSTEUERUNG,
    loese_bei_checkout,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - T4-A-Tests brauchen Test-DB"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _lege_zimmer_an(setup_engine: AsyncEngine, *, buchbar: bool) -> tuple[int, int]:
    """Ein Zimmer mit eigenem Raumtyp. Gibt ``(room_id, room_type_id)``."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        rt = RoomType(name=f"t4a-{suffix}", is_bookable=buchbar)
        session.add(rt)
        await session.flush()
        room = Room(number=f"t4a-{suffix}", room_type_id=rt.id)
        session.add(room)
        await session.commit()
        return room.id, rt.id


async def _raeum_auf(setup_engine: AsyncEngine, room_id: int, rt_id: int) -> None:
    """FK-sicher absteigend loeschen.

    Der Test committet, ein Rollback greift also nicht (Paragraph 5.60).
    Und er raeumt das Audit mit: ein Eintrag aus einem roten Lauf laesst
    den naechsten Lauf stillschweigend durchgehen (Paragraph 5.39).
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await session.execute(
            text("DELETE FROM business_audit WHERE target_type='room' AND target_id=:r"),
            {"r": room_id},
        )
        await session.execute(
            text("DELETE FROM manual_override WHERE room_id = :r"), {"r": room_id}
        )
        await session.execute(text("DELETE FROM occupancy WHERE room_id = :r"), {"r": room_id})
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": room_id})
        await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": rt_id})
        await session.commit()


@pytest_asyncio.fixture
async def zimmer(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    room_id, rt_id = await _lege_zimmer_an(setup_engine, buchbar=True)
    try:
        yield room_id
    finally:
        await _raeum_auf(setup_engine, room_id, rt_id)


@pytest_asyncio.fixture
async def bereich(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    """Ein Allgemeinbereich — nicht buchbarer Raumtyp."""
    room_id, rt_id = await _lege_zimmer_an(setup_engine, buchbar=False)
    try:
        yield room_id
    finally:
        await _raeum_auf(setup_engine, room_id, rt_id)


async def _setze_sperre(
    setup_engine: AsyncEngine, room_id: int, *, blocked: bool, bis_checkout: bool
) -> None:
    """Setzt die Felder direkt, ohne den Endpoint — fuer Dienst-Tests."""
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        room = await session.get(Room, room_id)
        assert room is not None
        room.guest_override_blocked = blocked
        room.guest_block_bis_checkout = bis_checkout
        await session.commit()


async def _lies_sperre(setup_engine: AsyncEngine, room_id: int) -> tuple[bool, bool]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        room = await session.get(Room, room_id)
        assert room is not None
        return room.guest_override_blocked, room.guest_block_bis_checkout


async def _audits(setup_engine: AsyncEngine, room_id: int, action: str) -> list[BusinessAudit]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rows = await session.execute(
            select(BusinessAudit)
            .where(BusinessAudit.target_type == "room")
            .where(BusinessAudit.target_id == room_id)
            .where(BusinessAudit.action == action)
        )
        return list(rows.scalars().all())


# ---------------------------------------------------------------------------
# 1. Der Loese-Dienst
# ---------------------------------------------------------------------------


async def test_sperre_bis_checkout_wird_beim_auszug_geloest(
    setup_engine: AsyncEngine, zimmer: int
) -> None:
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=True)

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        geloest = await loese_bei_checkout(session, zimmer, RoomStatus.OCCUPIED, RoomStatus.VACANT)
        await session.commit()

    assert geloest is True
    # **Beide** Felder fallen. Ein stehen gelassenes ``bis_checkout``
    # wuerde beim naechsten Setzen eine Absicht vorspiegeln.
    assert await _lies_sperre(setup_engine, zimmer) == (False, False)
    assert len(await _audits(setup_engine, zimmer, ACTION_GELOEST)) == 1


async def test_dauerhafte_sperre_bleibt_beim_auszug_stehen(
    setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Eine dauerhafte Sperre ist eine Entscheidung ueber das **Zimmer**.

    Sie zu loesen, weil ein Gast abreist, waere eine Vermutung ueber die
    Absicht — und zwar die falsche: wer dauerhaft gesperrt hat, hat sich
    gegen das Drehrad entschieden, nicht gegen diesen Gast.
    """
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=False)

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        geloest = await loese_bei_checkout(session, zimmer, RoomStatus.OCCUPIED, RoomStatus.VACANT)
        await session.commit()

    assert geloest is False
    assert await _lies_sperre(setup_engine, zimmer) == (True, False)
    # Ohne Wirkung kein Audit — ein Protokoll voller Nicht-Ereignisse
    # verdeckt die echten.
    assert await _audits(setup_engine, zimmer, ACTION_GELOEST) == []


async def test_andere_statuswechsel_loesen_nichts(setup_engine: AsyncEngine, zimmer: int) -> None:
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=True)

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        # Einzug, Reinigung, Sperre des Zimmers — keiner davon ist eine
        # Abreise.
        for vorher, nachher in (
            (RoomStatus.VACANT, RoomStatus.OCCUPIED),
            (RoomStatus.OCCUPIED, RoomStatus.CLEANING),
            (RoomStatus.RESERVED, RoomStatus.VACANT),
        ):
            assert await loese_bei_checkout(session, zimmer, vorher, nachher) is False
        await session.commit()

    assert await _lies_sperre(setup_engine, zimmer) == (True, True)


# ---------------------------------------------------------------------------
# 2. Der Endpoint
# ---------------------------------------------------------------------------


async def test_patch_setzt_sperre_bis_checkout(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    resp = await http_client.patch(
        f"/api/v1/rooms/{zimmer}/override-block-state",
        json={"blocked": True, "bis_checkout": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guest_override_blocked"] is True
    assert body["guest_block_bis_checkout"] is True
    assert await _lies_sperre(setup_engine, zimmer) == (True, True)


async def test_patch_ohne_bis_checkout_bleibt_dauerhaft(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Der Standard ist das bisherige Verhalten — ``bis_checkout`` fehlt."""
    resp = await http_client.patch(
        f"/api/v1/rooms/{zimmer}/override-block-state",
        json={"blocked": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["guest_block_bis_checkout"] is False
    assert await _lies_sperre(setup_engine, zimmer) == (True, False)


async def test_patch_bis_checkout_ohne_sperre_ist_422(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    resp = await http_client.patch(
        f"/api/v1/rooms/{zimmer}/override-block-state",
        json={"blocked": False, "bis_checkout": True},
    )
    assert resp.status_code == 422, resp.text
    assert "setzt eine Sperre voraus" in resp.json()["detail"]
    # Nichts geschrieben — die Abweisung steht vor jeder Mutation.
    assert await _lies_sperre(setup_engine, zimmer) == (False, False)


async def test_patch_bis_checkout_im_allgemeinbereich_ist_422(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, bereich: int
) -> None:
    """Ein Bereich hat keine Abreise — die Sperre wuerde nie enden.

    Dass der Loese-Dienst ihn nie zu sehen bekaeme (``sync_room_status``
    laesst nicht buchbare Raumtypen stehen), ist kein Ersatz fuer die
    Abweisung: genau dann waere die Sperre still und dauerhaft, obwohl
    die Oberflaeche „bis Check-out" verspricht.
    """
    resp = await http_client.patch(
        f"/api/v1/rooms/{bereich}/override-block-state",
        json={"blocked": True, "bis_checkout": True},
    )
    assert resp.status_code == 422, resp.text
    assert "Allgemeinbereich" in resp.json()["detail"]
    assert await _lies_sperre(setup_engine, bereich) == (False, False)

    # Die dauerhafte Sperre bleibt dort moeglich.
    ok = await http_client.patch(
        f"/api/v1/rooms/{bereich}/override-block-state",
        json={"blocked": True},
    )
    assert ok.status_code == 200, ok.text
    assert await _lies_sperre(setup_engine, bereich) == (True, False)


async def test_wechsel_von_dauerhaft_auf_bis_checkout_wirkt(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Die Idempotenz vergleicht beide Felder.

    Vorher stand im Endpoint nur ``old_blocked == payload.blocked``. Mit
    dem neuen Feld haette dieser Wechsel **nichts** getan und 200
    gemeldet — die Oberflaeche haette „bis Check-out" angezeigt, die
    Datenbank „dauerhaft". Genau die Sorte stiller Abweichung, die
    niemand nachprueft.
    """
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=False)

    resp = await http_client.patch(
        f"/api/v1/rooms/{zimmer}/override-block-state",
        json={"blocked": True, "bis_checkout": True},
    )
    assert resp.status_code == 200, resp.text
    assert await _lies_sperre(setup_engine, zimmer) == (True, True)


async def test_wechsel_widerruft_nicht_zweimal(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Widerrufen wird beim **Beginn** der Sperre, nicht bei jeder Aenderung.

    Ein Override, der nach dem Sperren angelegt wurde, kann nicht
    existieren — der Dienst weist ihn ab. Der Test legt ihn deshalb direkt
    an und prueft, dass der Wechsel auf ``bis_checkout`` ihn **nicht**
    anfasst: sonst waere jede Aenderung an der Form der Sperre ein zweiter
    Eingriff in die Override-Tabelle.
    """
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=False)

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        ov = ManualOverride(
            room_id=zimmer,
            setpoint=22,
            source=OverrideSource.FRONTEND_4H,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            reason="t4a-seed",
        )
        session.add(ov)
        await session.commit()
        ov_id = ov.id

    resp = await http_client.patch(
        f"/api/v1/rooms/{zimmer}/override-block-state",
        json={"blocked": True, "bis_checkout": True},
    )
    assert resp.status_code == 200, resp.text

    async with sessionmaker() as session:
        frisch = await session.get(ManualOverride, ov_id)
        assert frisch is not None
        assert frisch.revoked_at is None

    audits = await _audits(setup_engine, zimmer, "ROOM_OVERRIDE_BLOCK_TOGGLED")
    assert len(audits) == 1
    assert audits[0].new_value is not None
    assert audits[0].new_value["revoked_overrides_count"] == 0
    assert audits[0].new_value["bis_checkout"] is True


async def test_aufheben_setzt_bis_checkout_mit_zurueck(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=True)

    resp = await http_client.patch(
        f"/api/v1/rooms/{zimmer}/override-block-state",
        json={"blocked": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["guest_block_bis_checkout"] is False
    assert await _lies_sperre(setup_engine, zimmer) == (False, False)


# ---------------------------------------------------------------------------
# 3. Die Kette: ein echter Belegungs-Abgleich
# ---------------------------------------------------------------------------


async def test_belegungsabgleich_loest_die_sperre(setup_engine: AsyncEngine, zimmer: int) -> None:
    """Der Beweis, dass der Dienst **aufgerufen** wird.

    Die Tests oben zeigen, dass die Funktion das Richtige tut. Dass
    ``sync_room_status`` sie ruft, zeigt erst dieser: eine abgelaufene
    Belegung, ein Zimmer auf ``occupied``, ein Abgleich — und danach ist
    die Sperre weg. Ohne diese Stufe waere ein vergessener Aufruf ein
    gruener Lauf (Paragraph 5.55).
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    jetzt = datetime.now(tz=UTC)

    async with sessionmaker() as session:
        room = await session.get(Room, zimmer)
        assert room is not None
        room.status = RoomStatus.OCCUPIED
        room.guest_override_blocked = True
        room.guest_block_bis_checkout = True
        # Eine Belegung, die vorbei ist: der Abgleich leitet daraus
        # ``vacant`` ab.
        session.add(
            Occupancy(
                room_id=zimmer,
                check_in=jetzt - timedelta(days=2),
                check_out=jetzt - timedelta(hours=1),
                guest_count=1,
                source=OccupancySource.MANUAL,
            )
        )
        await session.commit()

    async with sessionmaker() as session:
        await occupancy_service.sync_room_status(session, zimmer, jetzt)
        await session.commit()

    sperre = await _lies_sperre(setup_engine, zimmer)
    assert sperre == (False, False), f"Sperre nach Abgleich: {sperre}"
    assert len(await _audits(setup_engine, zimmer, ACTION_GELOEST)) == 1


# ---------------------------------------------------------------------------
# 4. T4-A2 — das Haekchen im Uebersteuerungs-Dialog
#
# **Der Befund des Betreibers zu #340, als Test.** Der Weg ueber den
# Sperr-Knopf deckt den vereinbarten Fall nicht ab: dort beginnt die
# Sperre mit einem Widerruf aller Uebersteuerungen, und das trifft genau
# die, die die Rezeption gerade festsetzen will. Der erste Test unten ist
# der Beweis, dass dieser Weg es anders macht.
# ---------------------------------------------------------------------------


async def _belege(setup_engine: AsyncEngine, room_id: int) -> None:
    """Eine laufende Belegung plus ``status=occupied``.

    Beides ist noetig und aus verschiedenen Gruenden: ``frontend_checkout``
    braucht einen kommenden Check-out (``next_active_checkout``), und das
    OCCUPIED-Gate des Dienstes rechnet mit ``derive_room_status`` aus
    derselben Belegung. Das Statusfeld steht daneben fuer die Oberflaeche
    (Paragraph 5.53 — zwei Quellen, die der Abgleich zusammenhaelt).
    """
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    jetzt = datetime.now(tz=UTC)
    async with sessionmaker() as session:
        room = await session.get(Room, room_id)
        assert room is not None
        room.status = RoomStatus.OCCUPIED
        session.add(
            Occupancy(
                room_id=room_id,
                check_in=jetzt - timedelta(hours=2),
                check_out=jetzt + timedelta(days=2),
                guest_count=1,
                source=OccupancySource.MANUAL,
            )
        )
        await session.commit()


async def _overrides(setup_engine: AsyncEngine, room_id: int) -> list[ManualOverride]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rows = await session.execute(
            select(ManualOverride)
            .where(ManualOverride.room_id == room_id)
            .order_by(ManualOverride.id)
        )
        return list(rows.scalars().all())


async def test_haekchen_setzt_sperre_und_widerruft_die_uebersteuerung_nicht(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """**Der Kern von T4-A2.** 23 Grad plus Haekchen in einem Aufruf.

    Danach muss **beides** stehen: die Sperre auf dem Zimmer und die
    Uebersteuerung mit 23 Grad, nicht widerrufen. Der Weg ueber den
    Sperr-Knopf haette hier eine widerrufene Zeile hinterlassen — das war
    der Befund zu #340, und dieser Test ist die Gegenprobe dazu.
    """
    await _belege(setup_engine, zimmer)

    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={
            "setpoint": "23",
            "source": "frontend_checkout",
            "gast_sperre_bis_checkout": True,
        },
    )
    assert resp.status_code == 201, resp.text

    assert await _lies_sperre(setup_engine, zimmer) == (True, True)

    zeilen = await _overrides(setup_engine, zimmer)
    assert len(zeilen) == 1
    assert zeilen[0].revoked_at is None, "die Uebersteuerung wurde widerrufen — genau #340"
    assert zeilen[0].revoked_reason is None
    assert int(zeilen[0].setpoint) == 23
    assert zeilen[0].source == OverrideSource.FRONTEND_CHECKOUT


async def test_haekchen_schreibt_sein_audit_ohne_widerrufszahl(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Die Sperre ist nachlesbar, und zwar unter derselben Action wie beim
    Knopf — sonst waere "wer hat gesperrt" zwei Abfragen.

    Die fehlende ``revoked_overrides_count`` ist die Aussage: hier wurde
    bewusst nichts widerrufen.
    """
    await _belege(setup_engine, zimmer)
    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout", "gast_sperre_bis_checkout": True},
    )
    assert resp.status_code == 201, resp.text

    sperr_audits = await _audits(setup_engine, zimmer, "ROOM_OVERRIDE_BLOCK_TOGGLED")
    assert len(sperr_audits) == 1
    neu = sperr_audits[0].new_value
    assert neu is not None
    assert neu["blocked"] is True
    assert neu["bis_checkout"] is True
    assert neu["via"] == VIA_UEBERSTEUERUNG
    assert "revoked_overrides_count" not in neu

    set_audits = await _audits(setup_engine, zimmer, "MANUAL_OVERRIDE_SET")
    assert len(set_audits) == 1
    assert set_audits[0].new_value is not None
    assert set_audits[0].new_value["gast_sperre_bis_checkout"] is True


async def test_ohne_haekchen_bleibt_die_sperre_aus(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Der Standard ist AUS. Ohne das Feld passiert nichts Zusaetzliches —
    eine Uebersteuerung "Bis Check-out" ist fuer sich keine Sperre.
    """
    await _belege(setup_engine, zimmer)
    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout"},
    )
    assert resp.status_code == 201, resp.text
    assert await _lies_sperre(setup_engine, zimmer) == (False, False)
    assert await _audits(setup_engine, zimmer, "ROOM_OVERRIDE_BLOCK_TOGGLED") == []


async def test_haekchen_ohne_bis_checkout_ist_422(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Bei jeder anderen Dauer laeuft die Uebersteuerung aus, waehrend der
    Gast noch da ist — die Sperre bliebe stehen.

    Und: nach einem 422 darf **nichts** geschrieben sein. Die Abweisung
    steht deshalb vor dem Schreibvorgang.
    """
    await _belege(setup_engine, zimmer)
    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_24h", "gast_sperre_bis_checkout": True},
    )
    assert resp.status_code == 422, resp.text
    assert "Bis Check-out" in resp.json()["detail"]
    assert await _lies_sperre(setup_engine, zimmer) == (False, False)
    assert await _overrides(setup_engine, zimmer) == []


async def test_haekchen_im_allgemeinbereich_ist_422(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, bereich: int
) -> None:
    """Ein Bereich hat keine Abreise — die Sperre wuerde nie enden.

    Die Quelle waere hier ohnehin falsch, und der Dienst wuerde das
    abweisen. Dieser Satz sagt dem Leser aber, **was** nicht geht; der
    andere sagt nur, dass die Quelle nicht passt.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout", "gast_sperre_bis_checkout": True},
    )
    assert resp.status_code == 422, resp.text
    assert "Allgemeinbereich" in resp.json()["detail"]
    assert await _lies_sperre(setup_engine, bereich) == (False, False)


async def test_personal_darf_waehrend_der_sperre_weiter_setzen(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Die Sperre "bis Check-out" nimmt dem Gast das Rad, nicht der
    Rezeption die Eingabe.

    Sonst waere eine Korrektur der eigenen Eingabe nur ueber "aufheben,
    setzen, wieder sperren" moeglich — drei Handgriffe, bei denen der
    mittlere das Rad kurz freigibt.
    """
    await _belege(setup_engine, zimmer)
    erst = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout", "gast_sperre_bis_checkout": True},
    )
    assert erst.status_code == 201, erst.text

    zweit = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "21", "source": "frontend_checkout"},
    )
    assert zweit.status_code == 201, zweit.text
    assert await _lies_sperre(setup_engine, zimmer) == (True, True), "die Sperre bleibt stehen"

    aktiv = [o for o in await _overrides(setup_engine, zimmer) if o.revoked_at is None]
    assert len(aktiv) == 1
    assert int(aktiv[0].setpoint) == 21


async def test_dauerhafte_sperre_weist_auch_das_personal_ab(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Die dauerhafte Sperre bleibt, wie sie war: 409 fuer alle.

    Sie ist eine Entscheidung ueber das Zimmer, keine ueber einen Gast,
    und ihr Weg zurueck ist der Knopf in der Kopfzeile.
    """
    await _belege(setup_engine, zimmer)
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=False)

    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "ROOM_OVERRIDE_BLOCKED"
    assert await _overrides(setup_engine, zimmer) == []


@pytest.mark.parametrize("quelle", [OverrideSource.DEVICE, OverrideSource.DEVICE_MANUAL])
async def test_das_rad_bleibt_waehrend_der_sperre_abgewiesen(
    setup_engine: AsyncEngine, zimmer: int, quelle: OverrideSource
) -> None:
    """Der Gast dreht — und der Dienst weist ab, auch bei der Sperre
    "bis Check-out".

    Das ist die Haelfte von "zurueck auf 23 Grad": die Drehung erzeugt
    keinen Override. Die andere Haelfte steht im Test darunter.

    Geprueft wird der **Dienst**, weil dort die einzige Wahrheit liegt
    (AE-58). Der Vorab-Check im ``device_adapter`` liest unveraendert
    ``guest_override_blocked`` und greift damit bei beiden Formen; sein
    eigener Test liegt in ``test_device_adapter.py``.
    """
    await _belege(setup_engine, zimmer)
    await _setze_sperre(setup_engine, zimmer, blocked=True, bis_checkout=True)

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        with pytest.raises(override_service.RoomOverrideBlockedError):
            await override_service.create(
                session,
                room_id=zimmer,
                setpoint=Decimal("18"),
                source=quelle,
                expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            )


async def test_nach_der_abgewiesenen_drehung_gilt_weiter_23_grad(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """Die andere Haelfte: der Wert der Rezeption **ueberlebt** die
    Drehung.

    Damit ist "spaetestens mit dem naechsten Abgleich wieder 23 Grad"
    belegt, ohne einen Engine-Tick zu fahren: Layer 3 liest genau diese
    Zeile, und sie steht unveraendert da. Ein Test, der zusaetzlich einen
    Downlink prueft, braeuchte Geraete und wuerde dieselbe Zusicherung
    eine Ebene tiefer wiederholen.
    """
    await _belege(setup_engine, zimmer)
    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout", "gast_sperre_bis_checkout": True},
    )
    assert resp.status_code == 201, resp.text

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        with pytest.raises(override_service.RoomOverrideBlockedError):
            await override_service.create(
                session,
                room_id=zimmer,
                setpoint=Decimal("28"),
                source=OverrideSource.DEVICE,
                expires_at=datetime.now(tz=UTC) + timedelta(hours=4),
            )

    async with sessionmaker() as session:
        aktiv = await override_service.get_active(session, zimmer)
    assert aktiv is not None
    assert int(aktiv.setpoint) == 23


async def test_abreise_beendet_sperre_und_uebersteuerung_zusammen(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, zimmer: int
) -> None:
    """ "Bei Abreise enden Override und Sperre gemeinsam."

    Beide haengen am selben Ereignis und an derselben Stelle
    (``sync_room_status``): ``auto_revoke_on_checkout`` fuer die Zeile,
    ``loese_bei_checkout`` fuer die Sperre. Dieser Test fasst sie
    zusammen, weil "gemeinsam" die Zusicherung ist — zwei getrennt gruene
    Tests wuerden einen fehlenden der beiden Aufrufe nicht zeigen
    (Paragraph 5.55).
    """
    await _belege(setup_engine, zimmer)
    resp = await http_client.post(
        f"/api/v1/rooms/{zimmer}/overrides",
        json={"setpoint": "23", "source": "frontend_checkout", "gast_sperre_bis_checkout": True},
    )
    assert resp.status_code == 201, resp.text

    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)
    jetzt = datetime.now(tz=UTC)
    # Die Abreise vorziehen: dieselbe Belegung, Check-out in der
    # Vergangenheit. Der Abgleich leitet daraus "vacant" ab.
    async with sessionmaker() as session:
        await session.execute(
            text("UPDATE occupancy SET check_out = :c WHERE room_id = :r"),
            {"c": jetzt - timedelta(hours=1), "r": zimmer},
        )
        await session.commit()

    async with sessionmaker() as session:
        await occupancy_service.sync_room_status(session, zimmer, jetzt)
        await session.commit()

    assert await _lies_sperre(setup_engine, zimmer) == (False, False)
    zeilen = await _overrides(setup_engine, zimmer)
    assert len(zeilen) == 1
    assert zeilen[0].revoked_at is not None, "die Uebersteuerung laeuft weiter"
