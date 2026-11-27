"""event_log verdichten: Trockenlauf, echter Lauf, Rueckweg (27.11.2026).

**Warum das gegen die echte Datenbank laufen muss.** Das Werkzeug redet
mit dem TimescaleDB-Katalog (``timescaledb_information.chunks``,
``chunks_detailed_size``, ``compress_chunk``). Ein Doppelgaenger davon
waere eine Zusicherung ueber meine Vorstellung des Katalogs, nicht ueber
den Katalog — und genau dort lagen die beiden Fehlbefunde, die
Paragraph 5.68 meint.

**Der echte Lauf wird im Test zurueckgenommen.** Er faellt in dieselbe
Datenbank, in der 2300 andere Tests arbeiten; ein verdichtetes
``event_log`` und eine stehengebliebene ``compress``-Eigenschaft waeren
genau die Art Rest, die am 27.11.2026 einen fremden Test rot gemacht hat
(Paragraph 5.39). Das ``finally`` packt aus und schaltet ab.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path as FsPath

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from alembic import command
from heizung.models.enums import CommandReason, EventLogLayer
from heizung.models.event_log import EventLog
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.scripts import event_log_verdichten as werkzeug

DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "t-verd"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)


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


# ---------------------------------------------------------------------------
# Die Schalter — reine Pruefung, ohne Datenbank.
# ---------------------------------------------------------------------------


def _args(**kw: object) -> argparse.Namespace:
    grund = {"ausfuehren": False, "zuruecknehmen": False, "aelter_als_tage": 14}
    grund.update(kw)
    return argparse.Namespace(**grund)


def test_beide_schalter_zusammen_sind_kein_lauf(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--ausfuehren --zuruecknehmen`` ist ein Tippfehler, kein Lauf.

    Und ein Tippfehler, der die Tabelle zweimal anfasst. Geprueft wird
    ueber ``main``, aber **ohne** ``_verteile`` — ein zweiter Event-Loop
    in der Suite macht Schaden in einer anderen Datei (Paragraph 5.14,
    Nachtrag vom 01.11.).
    """
    monkeypatch.setattr("sys.argv", ["x", "--ausfuehren", "--zuruecknehmen"])
    monkeypatch.setattr(werkzeug, "_verteile", lambda _a: pytest.fail("darf nicht laufen"))
    assert werkzeug.main() == 2
    assert "keinen Lauf" in capsys.readouterr().out


def test_unter_sieben_tagen_bricht_ab(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sieben Tage ist das Chunk-Intervall — darunter liegt der laufende Chunk.

    Die Engine schreibt dort jede Minute hinein. Ein Werkzeug, das ihn
    verdichtet, weil jemand ``--aelter-als-tage 1`` getippt hat, greift in
    den laufenden Betrieb.
    """
    monkeypatch.setattr("sys.argv", ["x", "--ausfuehren", "--aelter-als-tage", "3"])
    monkeypatch.setattr(werkzeug, "_verteile", lambda _a: pytest.fail("darf nicht laufen"))
    assert werkzeug.main() == 2
    assert "laufenden Chunk" in capsys.readouterr().out


def test_die_vorgabe_ist_der_trockenlauf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ohne Schalter wird gezaehlt und nichts geaendert.

    Das ist die Zusicherung, auf die sich der Betreiber verlaesst, wenn er
    den Befehl aus dem RUNBOOK ohne Nachdenken eintippt.
    """
    gesehen: list[argparse.Namespace] = []
    monkeypatch.setattr("sys.argv", ["x"])
    monkeypatch.setattr(werkzeug, "_verteile", lambda a: (gesehen.append(a), 0)[1])
    assert werkzeug.main() == 0
    assert gesehen[0].ausfuehren is False
    assert gesehen[0].zuruecknehmen is False
    assert gesehen[0].aelter_als_tage == werkzeug.VORGABE_TAGE


# ---------------------------------------------------------------------------
# Gegen die Datenbank.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def alte_zeilen(setup_engine: AsyncEngine) -> AsyncIterator[int]:
    """Ein Zimmer mit Trace-Zeilen, die **20 Tage** zurueckliegen.

    Zwanzig Tage: jenseits der Vorgabe von 14, also im Zugriff des
    Werkzeugs, und in einem Chunk, in den der laufende Betrieb nicht mehr
    schreibt.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:6]
    basis = datetime.now(tz=UTC) - timedelta(days=20)

    async with maker() as session:
        rt = RoomType(name=f"{PREFIX}-rt-{short}", default_t_occupied=Decimal("22.0"))
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        session.add_all(
            [
                EventLog(
                    time=basis + timedelta(minutes=i),
                    room_id=room.id,
                    evaluation_id=uuid.uuid4(),
                    layer=EventLogLayer.HARD_CLAMP,
                    setpoint_in=Decimal("21.0"),
                    setpoint_out=Decimal("22.0"),
                    reason=CommandReason.VACANT_SETPOINT,
                    details={"quelle": "test", "nr": i},
                )
                for i in range(50)
            ]
        )
        await session.commit()
        room_id = room.id
        rt_id = rt.id

    try:
        yield room_id
    finally:
        async with maker() as session:
            # Erst auspacken: aus einem verdichteten Chunk zu loeschen
            # ist teuer und im Aufraeumen unnoetig.
            #
            # **Nur wenn es etwas auszupacken gibt.** ``decompress_chunk``
            # bricht auf einer Tabelle ohne eingeschaltete Verdichtung mit
            # „missing columnstore-enabled hypertable" ab, und das war der
            # Fehler im Aufraeumen des Trockenlauf-Tests, der gar nichts
            # verdichtet.
            verdichtet = await session.scalar(
                text(
                    "SELECT count(*) FROM timescaledb_information.chunks "
                    "WHERE hypertable_name = 'event_log' AND is_compressed"
                )
            )
            if verdichtet:
                await session.execute(
                    text(
                        "SELECT decompress_chunk(c, if_compressed => true) "
                        "FROM show_chunks('event_log') c"
                    )
                )
                await session.commit()
            await session.execute(text("ALTER TABLE event_log SET (timescaledb.compress = false)"))
            await session.commit()
            await session.execute(text("DELETE FROM event_log WHERE room_id = :r"), {"r": room_id})
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": room_id})
            await session.execute(text("DELETE FROM room_type WHERE id = :i"), {"i": rt_id})
            await session.commit()


async def test_event_log_ist_eine_hypertable(setup_engine: AsyncEngine) -> None:
    """Die Voraussetzung, auf der alles andere steht — geprueft, nicht angenommen."""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        assert await werkzeug._hypertable_vorhanden(session) is True


async def test_der_trockenlauf_aendert_nichts(
    alte_zeilen: int, setup_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zaehlen, nicht anfassen.

    Geprueft wird nicht nur der Rueckgabewert, sondern dass **danach kein
    Chunk verdichtet** ist. Ein Trockenlauf, der am Ende doch etwas tut,
    waere der teuerste Fehler dieses Werkzeugs.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        chunks = await werkzeug.lies_chunks(session, aelter_als_tage=14)
        assert chunks, "keine Chunks jenseits von 14 Tagen — Fixture greift nicht"
        assert await werkzeug._trockenlauf(session, tage=14) == 0

    async with maker() as session:
        danach = await werkzeug.lies_chunks(session, aelter_als_tage=14)
    assert not any(c.verdichtet for c in danach)
    ausgabe = capsys.readouterr().out
    assert "Trockenlauf" in ausgabe
    assert "unbekannt" in ausgabe  # noch kein Faktor dieser Datenbank


async def test_der_echte_lauf_verdichtet_und_laesst_die_zeilen_stehen(
    alte_zeilen: int, setup_engine: AsyncEngine
) -> None:
    """Der Kern: kleiner werden, **ohne** eine Zeile zu verlieren.

    Das ist der Unterschied zwischen Verdichten und Loeschen, und er ist
    der Grund, warum dieser Weg mit Paragraph 0 S3 vertraeglich ist.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        vorher = await session.scalar(
            text("SELECT count(*) FROM event_log WHERE room_id = :r"), {"r": alte_zeilen}
        )
        assert vorher == 50
        assert await werkzeug._ausfuehren(session, tage=14) == 0

    async with maker() as session:
        chunks = await werkzeug.lies_chunks(session, aelter_als_tage=14)
        assert any(c.verdichtet for c in chunks), "kein Chunk verdichtet"
        # **Die Zeilen sind noch da** — aus dem verdichteten Chunk
        # gelesen.
        nachher = await session.scalar(
            text("SELECT count(*) FROM event_log WHERE room_id = :r"), {"r": alte_zeilen}
        )
        assert nachher == 50
        # Und der Inhalt stimmt, nicht nur die Zahl.
        wert = await session.scalar(
            text("SELECT setpoint_out FROM event_log WHERE room_id = :r ORDER BY time LIMIT 1"),
            {"r": alte_zeilen},
        )
        assert wert == Decimal("22.0")


async def test_der_zweite_lauf_findet_nichts_mehr(
    alte_zeilen: int, setup_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wiederholbar: ein schon verdichteter Chunk bricht den Lauf nicht ab.

    Im Wartungsfenster wird ein Befehl auch zweimal getippt.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        assert await werkzeug._ausfuehren(session, tage=14) == 0
    capsys.readouterr()
    async with maker() as session:
        assert await werkzeug._ausfuehren(session, tage=14) == 0
    assert "Nichts zu tun" in capsys.readouterr().out


async def test_der_trockenlauf_nennt_den_faktor_dieser_datenbank(
    alte_zeilen: int, setup_engine: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nach dem ersten echten Lauf steht ein **gemessener** Faktor da.

    Vorher steht „unbekannt" — und das ist der Unterschied zwischen einem
    Befund und einer Zahl aus einer Vorpruefung an nachgebauten Daten
    (Paragraph 5.68).
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        await werkzeug._ausfuehren(session, tage=14)
    capsys.readouterr()
    async with maker() as session:
        assert await werkzeug._trockenlauf(session, tage=14) == 0
    ausgabe = capsys.readouterr().out
    assert "Faktor dieser Datenbank" in ausgabe
    assert "unbekannt" not in ausgabe


async def test_der_rueckweg_packt_wieder_aus(alte_zeilen: int, setup_engine: AsyncEngine) -> None:
    """``--zuruecknehmen`` ist der Rueckweg, den das Wartungsfenster braucht."""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        await werkzeug._ausfuehren(session, tage=14)
    async with maker() as session:
        assert await werkzeug._zuruecknehmen(session, tage=14) == 0
    async with maker() as session:
        chunks = await werkzeug.lies_chunks(session, aelter_als_tage=14)
        assert not any(c.verdichtet for c in chunks)
        nachher = await session.scalar(
            text("SELECT count(*) FROM event_log WHERE room_id = :r"), {"r": alte_zeilen}
        )
        assert nachher == 50
