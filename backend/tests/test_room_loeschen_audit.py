"""Ein Zimmer zu loeschen nimmt seinen Engine-Trace mit (27.11.2026).

**Der S3-Punkt, den der Betreiber zuerst geklaert haben wollte.**
``event_log.room_id`` haengt mit ``ON DELETE CASCADE`` an ``room.id``.
Loescht ein Administrator ein Zimmer, fuehrt die Datenbank den Cascade
aus: jede Trace-Zeile dieses Zimmers ist weg, fuer alle vergangenen Tage,
und niemand schreibt etwas darueber. Danach ist die Frage „warum war das
Zimmer kalt" nicht mehr beantwortbar.

Paragraph 0 S3 verlangt, dass jede Sollwert-Entscheidung im Trace steht
und dass es keine schnellen Pfade daran vorbei gibt. Eine Loeschung, die
den Trace entfernt, **ohne sich selbst zu protokollieren**, ist genau
dieser Pfad.

Diese Datei **belegt** das Verhalten — sie aendert es nicht. Dass der
Cascade laeuft, ist eine Eigenschaft des Schemas; ob ein Zimmer mit Trace
ueberhaupt loeschbar bleiben soll, ist eine Entscheidung des Betreibers
(Statuseintrag vom 27.11.2026). Was dieser PR hinzufuegt, ist die
Audit-Zeile: **was** verloren geht, mit Zahlen, vor dem Loeschen, in
derselben Transaktion — und in einer Tabelle, die **nicht** an ``room``
haengt und das Zimmer daher ueberlebt.

**Die Vorpruefung vom 27.11.2026 hat zusaetzlich gezeigt:** der Cascade
laeuft auch durch **verdichtete** Chunks durch. Verdichtung schuetzt den
Trace also nicht; sie macht ihn nur kleiner.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path as FsPath
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.auth.dependencies import get_current_user
from heizung.db import get_session
from heizung.main import app
from heizung.models.enums import (
    CommandReason,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    UserRole,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.tagesplan import TagesplanFenster
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "t-del"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)

#: So viele Trace-Zeilen bekommt das Zimmer. Die Zahl steht in der
#: Erwartung, damit der Test nicht „irgendwas wurde gezaehlt" prueft.
TRACE_ZEILEN = 12


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = FsPath(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DATABASE_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


class Aufbau:
    def __init__(self, room_id: int, nummer: str, rt_id: int) -> None:
        self.room_id = room_id
        self.nummer = nummer
        self.rt_id = rt_id


@pytest_asyncio.fixture
async def zimmer(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    """Ein Allgemeinbereich mit Trace, Zone, Uebersteuerung und Tagesplan.

    Vier der sieben Tabellen, die am Cascade haengen — genug, um zu
    zeigen, dass die Audit-Zeile sie **einzeln** nennt und nicht eine
    Gesamtzahl.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:6]
    jetzt = datetime.now(tz=UTC)

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}", is_bookable=False, default_t_occupied=Decimal("22.0")
        )
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Bar")
        session.add(zone)
        session.add_all(
            [
                EventLog(
                    time=jetzt - timedelta(minutes=i),
                    room_id=room.id,
                    evaluation_id=uuid.uuid4(),
                    layer=EventLogLayer.HARD_CLAMP,
                    setpoint_in=Decimal("21.0"),
                    setpoint_out=Decimal("22.0"),
                    reason=CommandReason.VACANT_SETPOINT,
                    details={"quelle": "test"},
                )
                for i in range(TRACE_ZEILEN)
            ]
        )
        session.add(
            ManualOverride(
                room_id=room.id,
                setpoint=Decimal("23.0"),
                source=OverrideSource.FRONTEND_24H,
                expires_at=jetzt + timedelta(hours=4),
            )
        )
        session.add(
            TagesplanFenster(
                room_id=room.id,
                von_minute=360,
                bis_minute=480,
                temperatur=Decimal("25.0"),
            )
        )
        await session.commit()
        ids = Aufbau(room.id, room.number, rt.id)

    try:
        yield ids
    finally:
        async with maker() as session:
            # Das Zimmer ist im Erfolgsfall weg; der Cascade hat seine
            # Kinder mitgenommen. Was bleibt, ist der Raumtyp und die
            # Audit-Zeile — die eine wird geloescht, die andere auch,
            # damit kein fremder Test sie zaehlt (Paragraph 5.39).
            await session.execute(
                text("DELETE FROM business_audit WHERE target_type = 'room' AND target_id = :r"),
                {"r": ids.room_id},
            )
            await session.execute(
                text("DELETE FROM event_log WHERE room_id = :r"), {"r": ids.room_id}
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            await session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": ids.rt_id})
            await session.commit()


@pytest_asyncio.fixture
async def admin_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        email="admin@example.invalid",
        password_hash="x",
        role=UserRole.ADMIN,
        is_active=True,
    )
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def _zaehle(engine: AsyncEngine, sql: str, werte: dict[str, Any]) -> int:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        return int(await session.scalar(text(sql), werte) or 0)


async def test_der_cascade_nimmt_den_trace_mit(
    zimmer: Aufbau, admin_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Der Beleg: nach dem Loeschen ist der Engine-Trace des Zimmers weg.

    Das ist **kein** Fehler im Code, sondern das, was das Schema sagt —
    und der Grund, warum es die Audit-Zeile braucht.
    """
    vorher = await _zaehle(
        setup_engine, "SELECT count(*) FROM event_log WHERE room_id = :r", {"r": zimmer.room_id}
    )
    assert vorher == TRACE_ZEILEN

    antwort = await admin_client.delete(f"/api/v1/rooms/{zimmer.room_id}")
    assert antwort.status_code == 204

    nachher = await _zaehle(
        setup_engine, "SELECT count(*) FROM event_log WHERE room_id = :r", {"r": zimmer.room_id}
    )
    assert nachher == 0, "der Cascade hat den Trace nicht mitgenommen — Schema geaendert?"


async def test_die_audit_zeile_nennt_die_zahlen_und_ueberlebt(
    zimmer: Aufbau, admin_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Was verloren geht, steht hinterher in Zahlen da.

    **Und die Zeile ueberlebt das Zimmer.** ``business_audit`` haengt
    nicht an ``room``; haette sie einen Cascade, wuerde die Zeile im
    selben Zug verschwinden, in dem sie von ihrem Verschwinden berichtet.
    """
    antwort = await admin_client.delete(f"/api/v1/rooms/{zimmer.room_id}")
    assert antwort.status_code == 204

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        zeile = (
            await session.execute(
                text(
                    "SELECT action, old_value, new_value FROM business_audit "
                    "WHERE target_type = 'room' AND target_id = :r "
                    "ORDER BY ts DESC LIMIT 1"
                ),
                {"r": zimmer.room_id},
            )
        ).first()
    assert zeile is not None, "keine Audit-Zeile zur Loeschung"
    assert zeile.action == "ROOM_DELETED"
    alt = zeile.old_value
    assert isinstance(alt, dict)
    assert alt["number"] == zimmer.nummer
    mit = alt["mit_geloescht"]
    assert isinstance(mit, dict)
    # Die Zahlen sind der Punkt der Zeile: ohne sie steht dort „ein
    # Zimmer wurde geloescht" und nicht „zwoelf Trace-Zeilen sind weg".
    assert mit["event_log"] == TRACE_ZEILEN
    assert mit["heating_zone"] == 1
    assert mit["manual_override"] == 1
    assert mit["tagesplan_fenster"] == 1
    assert mit["occupancy"] == 0


async def test_alle_cascade_tabellen_stehen_in_der_zeile(
    zimmer: Aufbau, admin_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Die Liste ist vollstaendig gegen das Schema — nicht gegen eine Erinnerung.

    Gefragt wird die Datenbank: welche Fremdschluessel auf ``room.id``
    haben ``ON DELETE CASCADE``? Genau die muss die Audit-Zeile nennen.
    Kommt eine Tabelle dazu, faellt dieser Test — und das ist sein Zweck,
    denn eine unvollstaendige Liste zaehlt still zu wenig.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        zeilen = (
            await session.execute(
                text("""
                SELECT DISTINCT src.relname AS tabelle
                FROM pg_constraint c
                JOIN pg_class src ON src.oid = c.conrelid
                JOIN pg_class ziel ON ziel.oid = c.confrelid
                WHERE c.contype = 'f'
                  AND ziel.relname = 'room'
                  AND c.confdeltype = 'c'
                  -- **Ohne die Chunks.** Jeder Chunk einer Hypertable
                  -- erbt den Fremdschluessel seiner Tabelle und liegt in
                  -- ``_timescaledb_internal``. Ohne diese Zeile zaehlt
                  -- die Abfrage ``_hyper_2032_10802_chunk`` als eigene
                  -- Tabelle — und der Test verlangt, sie in
                  -- CASCADE_TABELLEN nachzutragen.
                  AND src.relnamespace = 'public'::regnamespace
                """)
            )
        ).all()
    aus_dem_schema = {str(z.tabelle) for z in zeilen}
    assert aus_dem_schema, "kein CASCADE auf room gefunden — Abfrage prueft nichts"

    from heizung.api.v1.rooms import CASCADE_TABELLEN

    fehlen = aus_dem_schema - set(CASCADE_TABELLEN)
    assert not fehlen, (
        f"Diese Tabellen haengen mit ON DELETE CASCADE an room, werden in der "
        f"Audit-Zeile aber nicht gezaehlt: {sorted(fehlen)}. "
        "Nachtragen in CASCADE_TABELLEN (api/v1/rooms.py)."
    )
    zuviel = set(CASCADE_TABELLEN) - aus_dem_schema
    assert not zuviel, (
        f"Diese Tabellen stehen in CASCADE_TABELLEN, haengen aber nicht "
        f"(mehr) so an room: {sorted(zuviel)}."
    )


async def test_ein_zimmer_mit_aktiver_belegung_bleibt_geschuetzt(
    zimmer: Aufbau, admin_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Die bestehende Schranke bleibt — und sie schreibt **keine** Audit-Zeile.

    Eine Loeschung, die abgewiesen wird, hat nichts geloescht. Eine Zeile
    darueber waere ein Eintrag ohne Ereignis.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        jetzt = datetime.now(tz=UTC)
        await session.execute(
            text(
                "INSERT INTO occupancy (room_id, check_in, check_out, source, is_active) "
                "VALUES (:r, :ein, :aus, 'manual', true)"
            ),
            {
                "r": zimmer.room_id,
                "ein": jetzt - timedelta(hours=1),
                "aus": jetzt + timedelta(days=1),
            },
        )
        await session.commit()

    antwort = await admin_client.delete(f"/api/v1/rooms/{zimmer.room_id}")
    assert antwort.status_code == 409

    noch_da = await _zaehle(
        setup_engine, "SELECT count(*) FROM event_log WHERE room_id = :r", {"r": zimmer.room_id}
    )
    assert noch_da == TRACE_ZEILEN
    audit = await _zaehle(
        setup_engine,
        "SELECT count(*) FROM business_audit WHERE target_type = 'room' AND target_id = :r",
        {"r": zimmer.room_id},
    )
    assert audit == 0

    async with maker() as session:
        await session.execute(
            text("DELETE FROM occupancy WHERE room_id = :r"), {"r": zimmer.room_id}
        )
        await session.commit()
