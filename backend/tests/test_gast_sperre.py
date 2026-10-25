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
from heizung.services import occupancy_service
from heizung.services.gast_sperre import ACTION_GELOEST, loese_bei_checkout

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
