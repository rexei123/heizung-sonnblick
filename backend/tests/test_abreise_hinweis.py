"""Abreise ueberschritten: wer in die Liste kommt und wer nicht (27.11.2026).

**Der Fall** steht im Handbuch („Abreise verschiebt sich"): ein Gast
bleibt laenger, niemand aendert das Datum, die Steuerung setzt das Zimmer
auf frei. Der Hinweis soll genau die Zimmer nennen, bei denen das gerade
passiert sein kann — und keine anderen, sonst ist er nach drei Tagen
Hintergrundrauschen (Paragraph 5.79).

**Die Uhr ist ein Argument.** ``lies_abreisen`` nimmt ``jetzt``; alle
Zeiten im Prueffall sind **Abstaende** davon. Ein festes Datum waere ein
Ablaufdatum, und eine zweite Uhr im Prueffall waere die Falle aus
Paragraph 5.59 in beide Richtungen.

**Was hier bewusst nicht geprueft wird:** ob der Gast wirklich noch da
ist. Das weiss nur die Rezeption. Der Dienst sammelt Spuren und faellt
kein Urteil — und die Tests pruefen die Spuren, nicht das Urteil.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    EventLogLayer,
    OccupancySource,
    OverrideSource,
    RoomStatus,
    UserRole,
)
from heizung.models.event_log import EventLog
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.user import User
from heizung.services import abreise_hinweis

DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "t-abr"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)

#: Der Augenblick, aus dem gerechnet wird. Aus der echten Uhr, damit die
#: Zeilen in der Hypertable nicht in ferner Vergangenheit liegen — alle
#: Angaben darunter sind **Abstaende** davon.
JETZT = datetime.now(tz=UTC).replace(microsecond=0)


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


class Zimmer:
    """Ein angelegtes Zimmer samt seiner Kennung."""

    def __init__(self, room_id: int, nummer: str) -> None:
        self.room_id = room_id
        self.nummer = nummer


@contextlib.asynccontextmanager
async def _haus(engine: AsyncEngine) -> AsyncIterator[tuple[Any, list[int]]]:
    """Ein Raumtyp und eine Liste, in die angelegte Zimmer wandern.

    Aufgeraeumt wird **von Hand** (Paragraph 5.39): die Zeilen sind
    festgeschrieben, ein ``rollback`` nimmt sie nicht zurueck.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:6]
    raeume: list[int] = []

    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}", is_bookable=True, default_t_occupied=Decimal("22.0")
        )
        session.add(rt)
        await session.commit()
        rt_id = rt.id

    class Hilfe:
        """Legt Zimmer, Belegungen und Spuren an — je Aufruf committet."""

        def __init__(self) -> None:
            self.lfd = 0

        async def zimmer(self) -> Zimmer:
            self.lfd += 1
            nummer = f"{PREFIX}{short}-{self.lfd}"
            async with maker() as session:
                room = Room(number=nummer, room_type_id=rt_id, status=RoomStatus.VACANT)
                session.add(room)
                await session.commit()
                raeume.append(room.id)
                return Zimmer(room.id, nummer)

        async def belegung(
            self, z: Zimmer, *, von_h: float, bis_h: float, aktiv: bool = True
        ) -> None:
            """Belegung in Stunden **relativ zu** ``JETZT`` (negativ = vorbei)."""
            async with maker() as session:
                session.add(
                    Occupancy(
                        room_id=z.room_id,
                        check_in=JETZT + timedelta(hours=von_h),
                        check_out=JETZT + timedelta(hours=bis_h),
                        source=OccupancySource.MANUAL,
                        is_active=aktiv,
                    )
                )
                await session.commit()

        async def drehrad_abgelehnt(self, z: Zimmer, *, vor_h: float) -> None:
            """Eine abgelehnte Drehrad-Verstellung (Paragraph 5.52).

            Off-Pipeline: eigene ``evaluation_id``, kein Sollwert, keine
            Steuerwirkung — so, wie ``device_adapter`` sie schreibt.
            """
            async with maker() as session:
                session.add(
                    EventLog(
                        time=JETZT - timedelta(hours=vor_h),
                        room_id=z.room_id,
                        evaluation_id=uuid.uuid4(),
                        layer=EventLogLayer.MANUAL_OVERRIDE_BLOCKED,
                        details={"source": "test", "grund": "room_not_occupied"},
                    )
                )
                await session.commit()

        async def uebersteuerung(
            self, z: Zimmer, *, gesetzt_vor_h: float, laeuft_noch_h: float
        ) -> None:
            async with maker() as session:
                session.add(
                    ManualOverride(
                        room_id=z.room_id,
                        setpoint=Decimal("23.0"),
                        source=OverrideSource.FRONTEND_24H,
                        created_at=JETZT - timedelta(hours=gesetzt_vor_h),
                        expires_at=JETZT + timedelta(hours=laeuft_noch_h),
                    )
                )
                await session.commit()

    try:
        yield Hilfe(), raeume
    finally:
        async with maker() as session:
            if raeume:
                await session.execute(
                    text("DELETE FROM event_log WHERE room_id = ANY(:r)"), {"r": raeume}
                )
                await session.execute(
                    text("DELETE FROM manual_override WHERE room_id = ANY(:r)"), {"r": raeume}
                )
                await session.execute(
                    text("DELETE FROM occupancy WHERE room_id = ANY(:r)"), {"r": raeume}
                )
                await session.execute(text("DELETE FROM room WHERE id = ANY(:r)"), {"r": raeume})
            await session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt_id})
            await session.commit()


async def _lies(engine: AsyncEngine) -> list[abreise_hinweis.AbreiseBefund]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        return await abreise_hinweis.lies_abreisen(session, jetzt=JETZT)


# ---------------------------------------------------------------------------
# Wer in die Liste kommt.
# ---------------------------------------------------------------------------


async def test_eine_verstrichene_abreise_kommt_in_die_liste(setup_engine: AsyncEngine) -> None:
    """Drei Stunden her, keine neue Belegung — der Fall, um den es geht."""
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-3)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert len(befunde) == 1
        assert befunde[0].zimmer == z.nummer
        assert befunde[0].stunden_her == 3
        assert befunde[0].zeichen == "keines"
        assert befunde[0].vielleicht_belegt is False


async def test_eine_laufende_belegung_nimmt_das_zimmer_heraus(setup_engine: AsyncEngine) -> None:
    """Der Gast ist angemeldet — dann ist nichts zu tun.

    Das ist der Fall „Abreise verlaengert, Liste nachgezogen": die alte
    Belegung ist vorbei, eine neue laeuft. Ohne diese Bedingung stuende
    das Zimmer im Hinweis, obwohl es genau richtig gefuehrt ist.
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-3)
        await h.belegung(z, von_h=-3, bis_h=24)

        assert [b for b in await _lies(setup_engine) if b.room_id == z.room_id] == []


async def test_eine_alte_abreise_faellt_aus_dem_fenster(setup_engine: AsyncEngine) -> None:
    """Dreissig Stunden her — die Liste waechst nicht mit den Tagen."""
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-72, bis_h=-30)

        assert [b for b in await _lies(setup_engine) if b.room_id == z.room_id] == []


async def test_eine_kuenftige_abreise_ist_kein_fall(setup_engine: AsyncEngine) -> None:
    """Der Gast ist noch da und das steht auch so in der Liste."""
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-24, bis_h=12)

        assert [b for b in await _lies(setup_engine) if b.room_id == z.room_id] == []


async def test_eine_zurueckgezogene_belegung_ist_keine_abreise(setup_engine: AsyncEngine) -> None:
    """``is_active = False`` ist eine Korrektur, keine Abreise.

    Eine abgesagte Buchung hat ein Abreisedatum in der Vergangenheit wie
    jede andere; sie als Abreise zu lesen wuerde die Liste mit Zimmern
    fuellen, in denen niemand war.
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-3, aktiv=False)

        assert [b for b in await _lies(setup_engine) if b.room_id == z.room_id] == []


async def test_die_juengste_abreise_steht_oben(setup_engine: AsyncEngine) -> None:
    async with _haus(setup_engine) as (h, _):
        alt = await h.zimmer()
        neu = await h.zimmer()
        await h.belegung(alt, von_h=-48, bis_h=-20)
        await h.belegung(neu, von_h=-48, bis_h=-2)

        unsere = [b for b in await _lies(setup_engine) if b.room_id in (alt.room_id, neu.room_id)]
        assert [b.room_id for b in unsere] == [neu.room_id, alt.room_id]


async def test_von_zwei_abreisen_zaehlt_die_juengste(setup_engine: AsyncEngine) -> None:
    """Zwei vorbei — gemeldet wird die, die naeher liegt.

    Sonst stuende im Hinweis „vor 20 Stunden" an einem Zimmer, das vor
    zwei Stunden abgereist ist, und die Zahl waere nicht die, nach der
    jemand sucht.
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-72, bis_h=-20)
        await h.belegung(z, von_h=-19, bis_h=-2)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert len(befunde) == 1
        assert befunde[0].stunden_her == 2


# ---------------------------------------------------------------------------
# Die Spuren.
# ---------------------------------------------------------------------------


async def test_eine_abgelehnte_drehradverstellung_ist_eine_spur(
    setup_engine: AsyncEngine,
) -> None:
    """Jemand hat gedreht, nachdem das Zimmer als frei gefuehrt wurde.

    Das ist der staerkste Hinweis, den die Anlage auf einen anwesenden
    Gast hat: das OCCUPIED-Tor (AE-58) hat die Verstellung verworfen und
    den Versuch festgehalten (Paragraph 5.52).
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-5)
        await h.drehrad_abgelehnt(z, vor_h=1)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert befunde[0].zeichen == "drehrad"
        assert befunde[0].vielleicht_belegt is True


async def test_eine_verstellung_vor_der_abreise_ist_keine_spur(
    setup_engine: AsyncEngine,
) -> None:
    """Die Spur muss **nach** der Abreise liegen.

    Vor der Abreise war der Gast angemeldet; eine Ablehnung von damals
    sagt nichts darueber, ob er heute noch da ist. Ohne den Vergleich
    truege jedes Zimmer mit Drehrad-Historie eine Spur.
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-5)
        await h.drehrad_abgelehnt(z, vor_h=10)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert befunde[0].zeichen == "keines"


async def test_eine_laufende_uebersteuerung_ist_eine_spur(setup_engine: AsyncEngine) -> None:
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-5)
        await h.uebersteuerung(z, gesetzt_vor_h=2, laeuft_noch_h=10)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert befunde[0].zeichen == "uebersteuerung"


async def test_eine_abgelaufene_uebersteuerung_ist_keine_spur(setup_engine: AsyncEngine) -> None:
    """Eine Wunschtemperatur, die nicht mehr wirkt, sagt nichts ueber jetzt."""
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-5)
        await h.uebersteuerung(z, gesetzt_vor_h=4, laeuft_noch_h=-1)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert befunde[0].zeichen == "keines"


async def test_das_drehrad_schlaegt_die_uebersteuerung(setup_engine: AsyncEngine) -> None:
    """Liegt beides vor, ist die Spur des **Gastes** die Nachricht.

    „Wunschtemperatur gesetzt" heisst, die Rezeption weiss es schon.
    „Jemand hat gedreht" heisst, dass jemand im Zimmer war — und das ist
    der Satz, der die Belegung in Frage stellt.
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-5)
        await h.drehrad_abgelehnt(z, vor_h=1)
        await h.uebersteuerung(z, gesetzt_vor_h=2, laeuft_noch_h=10)

        befunde = [b for b in await _lies(setup_engine) if b.room_id == z.room_id]
        assert befunde[0].zeichen == "drehrad"


async def test_zimmer_ohne_spur_bleiben_in_der_liste(setup_engine: AsyncEngine) -> None:
    """Die Spur filtert nicht, sie sortiert.

    Die meisten Gaeste drehen nicht am Thermostat. Ein Hinweis, der nur
    Zimmer mit Spur zeigt, verschweigt genau die stillen Faelle — und das
    sind die, bei denen abends niemand gewarnt war (Paragraph 5.55).
    """
    async with _haus(setup_engine) as (h, _):
        mit = await h.zimmer()
        ohne = await h.zimmer()
        await h.belegung(mit, von_h=-48, bis_h=-5)
        await h.belegung(ohne, von_h=-48, bis_h=-5)
        await h.drehrad_abgelehnt(mit, vor_h=1)

        ids = {b.room_id for b in await _lies(setup_engine)}
        assert mit.room_id in ids
        assert ohne.room_id in ids


# ---------------------------------------------------------------------------
# Durch den Endpunkt.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1,
        email="mitarbeiter@example.invalid",
        password_hash="x",
        role=UserRole.MITARBEITER,
        is_active=True,
    )
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
    app.dependency_overrides.pop(get_current_user, None)


async def test_das_dashboard_liefert_die_zimmer(
    setup_engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    """Die Kacheln und der Hinweis kommen aus **einer** Antwort.

    Der Endpunkt rechnet mit ``datetime.now()``; der Prueffall liegt
    deshalb bewusst zwei Stunden zurueck und nicht an der Fenstergrenze.
    """
    async with _haus(setup_engine) as (h, _):
        z = await h.zimmer()
        await h.belegung(z, von_h=-48, bis_h=-2)
        await h.drehrad_abgelehnt(z, vor_h=1)

        antwort = await client.get("/api/v1/dashboard/kpi")
        assert antwort.status_code == 200
        unsere = [e for e in antwort.json()["abreise_zimmer"] if e["room_id"] == z.room_id]
        assert len(unsere) == 1
        assert unsere[0]["zimmer"] == z.nummer
        assert unsere[0]["zeichen"] == "drehrad"
        assert unsere[0]["stunden_her"] >= 2
