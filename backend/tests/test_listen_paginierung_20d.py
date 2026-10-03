"""Sprint 20d (B-20c-2) — Zimmer, Raumtypen und Belegungen vollstaendig lesen.

**Der Befund, am 02.10.2026 auf dem Server gemessen:**

```
SELECT count(*) FROM occupancy WHERE is_active;  -->  959
```

Die Belegungen-Seite stand auf ``limit: 200`` und hat im Bereich „Alle"
**200 von 959** gezeigt, ohne das zu sagen. 759 fehlten. Das ist derselbe
Befund wie bei den Geraeten (B-20c-1, Sprint 20c), nur vier Mal so gross
und schon laenger im Betrieb.

Zimmer und Raumtypen hatten denselben Default 100 und vier Aufrufer mit
drei verschiedenen Antworten darauf (1000, 1000, 200, nichts) — latent,
weil 45 Zimmer unter 100 liegen.

Diese Datei haelt vier Dinge fest, in dieser Reihenfolge:

1. **Zimmer und Raumtypen kommen ueber Seiten vollstaendig zurueck**, jede
   Zeile genau einmal. Das ist die Zusicherung, auf der ``alleSeiten`` im
   Frontend aufsitzt.
2. **Die Belegungs-Antwort traegt eine Gesamtzahl**, und die gehoert zu
   **denselben** Filtern wie die Seite. Ohne sie kann die Oberflaeche nicht
   „N von M" sagen; mit einer Gesamtzahl zu *anderen* Filtern sagt sie es
   falsch.
3. **Die Sortierung der Belegungen ist eindeutig.** Das ist der Test, der
   ohne T1 rot ist: vorher stand dort ``order_by(Occupancy.check_in)``
   allein, und ``check_in`` ist nicht eindeutig — an einem Anreisetag haben
   Dutzende Buchungen denselben Wert. Postgres gibt dann keine garantierte
   Reihenfolge, und zwischen zwei Seiten kann eine Zeile doppelt erscheinen
   und eine andere gar nicht.
4. **Beide Richtungen** (``asc``/``desc``) bleiben ueber Seiten
   verlustfrei.

**Leftover-fest (§5.39).** Die Test-Datenbank enthaelt Zimmer, Raumtypen
und Belegungen aus anderen Test-Dateien. Keine Zusicherung hier rechnet mit
einer absoluten Gesamtzahl der Tabelle; jede rechnet mit **eigenen IDs**
oder grenzt per Filter auf die eigenen Zeilen ein. Dazu raeumt eine Fixture
die eigenen Zeilen nach jedem Test weg.

**Warum die Belegungs-Tests auf ``room_id`` filtern:** ``total`` ist die
Gesamtzahl zu den uebergebenen Filtern. Ohne Filter waere das die ganze
Tabelle einschliesslich fremder Zeilen — die Zusicherung „total == 201"
haenge dann an der Ausfuehrungsreihenfolge der Suite. Mit ``room_id`` auf
dem eigenen Zimmer ist die Zahl exakt und von Leftovers unabhaengig.

Folgt der DB-Skip-Konvention von ``test_devices_liste_vollstaendig``: skip
lokal ohne ``DATABASE_URL`` (§5.50 — lokal mit Postgres laufen lassen, nicht
nur skippen; hier nicht moeglich, B-18-5).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"

# Der Server-Default aller drei Endpoints (``rooms.py:97``,
# ``room_types.py:80``, ``occupancies.py:``). Steht hier als Konstante,
# damit nicht mehrere Tests dieselbe 100 von Hand tragen.
DEFAULT_LIMIT = 100

# Fester Zeitanker statt ``datetime.now`` — die Belegungs-Tests legen
# Zeitstempel an und vergleichen Reihenfolgen. Ein beweglicher Anker macht
# Vergleiche von der Uhrzeit des Laufs abhaengig (§5.59).
ANKER = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

# IDs, die diese Datei angelegt hat — fuer das Aufraeumen nach jedem Test.
_rooms: list[int] = []
_room_types: list[int] = []
_occupancies: list[int] = []


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL_PRESENT:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _aufraeumen(engine: AsyncEngine) -> AsyncIterator[None]:
    """Loescht nach jedem Test die eigenen Zeilen.

    Geloescht wird nur nach **eigenen IDs** (§5.39) und in FK-sicherer
    Reihenfolge: Belegungen vor Zimmern, Zimmer vor Raumtypen
    (``room.room_type_id`` ist ``ondelete=RESTRICT``).

    Die Tests committen, ein Rollback greift also nicht.
    """
    for liste in (_rooms, _room_types, _occupancies):
        liste.clear()
    try:
        yield
    finally:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            if _occupancies:
                await session.execute(delete(Occupancy).where(Occupancy.id.in_(list(_occupancies))))
            if _rooms:
                await session.execute(delete(Room).where(Room.id.in_(list(_rooms))))
            if _room_types:
                await session.execute(delete(RoomType).where(RoomType.id.in_(list(_room_types))))
            await session.commit()
        for liste in (_rooms, _room_types, _occupancies):
            liste.clear()


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed-Helfer
# ---------------------------------------------------------------------------


async def _seed_room_type(engine: AsyncEngine, *, suffix: str) -> int:
    """Ein Raumtyp. schema_constraint: ``room_type.name`` max 100 chars."""
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        rt = RoomType(name=f"20d-{suffix}", default_t_occupied=Decimal("21.0"))
        session.add(rt)
        await session.commit()
        rt_id = int(rt.id)
    _room_types.append(rt_id)
    return rt_id


async def _seed_room_types(engine: AsyncEngine, anzahl: int) -> list[int]:
    """``anzahl`` Raumtypen mit eindeutigem Namen.

    schema_constraint: ``room_type.name`` ist ``unique`` und max 100 chars.
    Aufbau ist ``20d-`` + 8 Hex + ``-`` + 4 Stellen = 17 Zeichen (§5.49).
    """
    suffix = uuid.uuid4().hex[:8]
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        typen = [
            RoomType(name=f"20d-{suffix}-{i:04d}", default_t_occupied=Decimal("21.0"))
            for i in range(anzahl)
        ]
        session.add_all(typen)
        await session.commit()
        ids = [int(t.id) for t in typen]
    _room_types.extend(ids)
    return ids


async def _seed_rooms(engine: AsyncEngine, anzahl: int, *, room_type_id: int) -> list[int]:
    """``anzahl`` Zimmer mit eindeutiger Nummer.

    schema_constraint: ``room.number`` ist ``unique`` und max **20** chars.
    Aufbau ist 8 Hex Lauf-Suffix + ``-`` + 4 Stellen Zaehler = 13 Zeichen
    (§5.18/§5.49).

    Die Nummern beginnen bewusst **nicht** mit einer Ziffer: der Endpoint
    sortiert ueber einen numerischen Praefix mit ``NULLS LAST`` und faellt
    danach auf ``number`` zurueck. So liegen die eigenen Zimmer als Block
    am Ende und die Reihenfolge innerhalb des Blocks ist die der Nummern —
    damit ist die Sortier-Zusicherung pruefbar, ohne von fremden Zeilen
    abzuhaengen.
    """
    suffix = uuid.uuid4().hex[:8]
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        zimmer = [
            Room(number=f"{suffix}-{i:04d}", room_type_id=room_type_id, floor=None)
            for i in range(anzahl)
        ]
        session.add_all(zimmer)
        await session.commit()
        ids = [int(z.id) for z in zimmer]
    _rooms.extend(ids)
    return ids


async def _seed_occupancies(
    engine: AsyncEngine,
    anzahl: int,
    *,
    room_id: int,
    gleicher_check_in: bool = False,
) -> list[int]:
    """``anzahl`` aktive Belegungen fuer **ein** Zimmer.

    Ueberlappende Zeitraeume sind hier Absicht: ``has_overlap`` prueft nur
    im POST-Endpoint, dieser Seed schreibt direkt. Geprueft wird die
    Paginierung, nicht die fachliche Belegungs-Regel.

    ``gleicher_check_in=True`` gibt **allen** Zeilen denselben ``check_in``.
    Das ist der Fall, der die Sortierung auf die Probe stellt: ohne den
    zweiten Schluessel ``id`` ist die Reihenfolge dann nicht definiert.
    """
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        belegungen = [
            Occupancy(
                room_id=room_id,
                check_in=ANKER if gleicher_check_in else ANKER + timedelta(hours=i),
                check_out=ANKER + timedelta(days=1, hours=i),
                is_active=True,
            )
            for i in range(anzahl)
        ]
        session.add_all(belegungen)
        await session.commit()
        ids = [int(b.id) for b in belegungen]
    _occupancies.extend(ids)
    return ids


# ---------------------------------------------------------------------------
# Abruf-Helfer
# ---------------------------------------------------------------------------


async def _alle_seiten_ids(
    client: httpx.AsyncClient,
    pfad: str,
    *,
    seitengroesse: int,
    params: dict[str, Any] | None = None,
) -> list[int]:
    """IDs ueber alle Seiten — dieselbe Schleife wie ``alleSeiten`` im Frontend.

    Bewusst nachgebaut und nicht nur „eine grosse Seite geholt": geprueft
    werden soll, dass die Paginierung **als Verfahren** vollstaendig ist,
    nicht dass ein grosses ``limit`` zufaellig reicht.
    """
    ids: list[int] = []
    offset = 0
    while True:
        anfrage = dict(params or {})
        anfrage.update({"limit": seitengroesse, "offset": offset})
        resp = await client.get(pfad, params=anfrage)
        assert resp.status_code == 200, resp.text
        teil = resp.json()
        assert isinstance(teil, list), f"{pfad} liefert keine nackte Liste mehr"
        ids.extend(int(z["id"]) for z in teil)
        if len(teil) < seitengroesse:
            return ids
        offset += seitengroesse


async def _belegungs_seite(
    client: httpx.AsyncClient, *, limit: int, offset: int, **filter_: Any
) -> dict[str, Any]:
    resp = await client.get(
        "/api/v1/occupancies", params={"limit": limit, "offset": offset, **filter_}
    )
    assert resp.status_code == 200, resp.text
    daten = resp.json()
    assert isinstance(daten, dict), "Belegungen liefern einen Envelope, keine Liste"
    return daten


async def _alle_belegungen(
    client: httpx.AsyncClient, *, seitengroesse: int, **filter_: Any
) -> tuple[list[int], int]:
    """(IDs ueber alle Seiten, ``total`` der ersten Seite).

    Die Abbruchbedingung ist dieselbe wie in ``useOccupanciesSeiten``:
    weiterblaettern, solange ``geladen < total`` **und** die Seite nicht
    leer war.
    """
    ids: list[int] = []
    offset = 0
    total = 0
    while True:
        seite = await _belegungs_seite(client, limit=seitengroesse, offset=offset, **filter_)
        if offset == 0:
            total = int(seite["total"])
        ids.extend(int(o["id"]) for o in seite["items"])
        if not seite["items"] or len(ids) >= total:
            return ids, total
        offset = len(ids)


# ---------------------------------------------------------------------------
# 1. Zimmer und Raumtypen: vollstaendig ueber Seiten
# ---------------------------------------------------------------------------


async def test_ohne_limit_liefern_zimmer_und_raumtypen_hoechstens_100(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Der Server-Default ist 100 — der Grund fuer die Client-Schleife.

    Das ist **kein** Fehler der Endpoints: ein paginierter Endpoint soll
    eine Seite liefern. Der Fehler lag darin, dass die Oberflaeche diese
    Seite fuer die ganze Liste genommen hat.

    Wer den Default hier aendert, aendert die Annahme, auf der
    ``frontend/src/lib/api/alle-seiten.ts`` aufsitzt — und sieht es an
    diesem Test.
    """
    rt = await _seed_room_type(engine, suffix=uuid.uuid4().hex[:8])
    await _seed_rooms(engine, 101, room_type_id=rt)
    await _seed_room_types(engine, 101)

    for pfad in ("/api/v1/rooms", "/api/v1/room-types"):
        resp = await client.get(pfad)
        assert resp.status_code == 200, resp.text
        assert len(resp.json()) == DEFAULT_LIMIT, f"{pfad} Default nicht mehr 100"


async def test_101_zimmer_kommen_ueber_seiten_vollstaendig_zurueck(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Jedes der 101 Zimmer genau einmal — keine Luecke, keine Dopplung.

    Absichtlich mit kleinen Seiten (25): 101 eigene Zimmer plus Bestand
    sind so mindestens fuenf Seiten, also vier Uebergaenge, an denen etwas
    verloren gehen koennte.

    Die 101 ist die Zahl aus dem Auftrag und hier gefahrlos, weil die
    Zusicherung auf **eigenen IDs** liegt und nicht auf einer Gesamtzahl
    der Tabelle (§5.39).
    """
    rt = await _seed_room_type(engine, suffix=uuid.uuid4().hex[:8])
    eigene = await _seed_rooms(engine, 101, room_type_id=rt)

    alle = await _alle_seiten_ids(client, "/api/v1/rooms", seitengroesse=25)

    assert len(alle) == len(set(alle)), "eine ID doppelt -> Sortierung nicht eindeutig"
    fehlende = set(eigene) - set(alle)
    assert not fehlende, f"{len(fehlende)} Zimmer fehlen in der paginierten Liste"


async def test_101_raumtypen_kommen_ueber_seiten_vollstaendig_zurueck(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Dasselbe fuer Raumtypen. Sortierung auf ``id``, also eindeutig."""
    eigene = await _seed_room_types(engine, 101)

    alle = await _alle_seiten_ids(client, "/api/v1/room-types", seitengroesse=25)

    assert len(alle) == len(set(alle))
    assert not set(eigene) - set(alle)
    assert alle == sorted(alle), "Raumtypen sind nach id aufsteigend sortiert"


# ---------------------------------------------------------------------------
# 2. Belegungen: Envelope mit Gesamtzahl
# ---------------------------------------------------------------------------


async def test_201_belegungen_mit_korrektem_total(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """201 Belegungen, drei Seiten, ``total`` auf jeder Seite gleich 201.

    Der Befund war, dass die Oberflaeche 200 von 959 zeigte, ohne es zu
    sagen. ``total`` ist die Zahl, mit der sie es sagen kann — und sie muss
    auf **jeder** Seite stimmen, nicht nur auf der ersten, weil die
    Oberflaeche nach „Weitere laden" aus der juengsten Antwort liest.
    """
    rt = await _seed_room_type(engine, suffix=uuid.uuid4().hex[:8])
    (zimmer,) = await _seed_rooms(engine, 1, room_type_id=rt)
    eigene = await _seed_occupancies(engine, 201, room_id=zimmer)

    ids, total = await _alle_belegungen(client, seitengroesse=100, room_id=zimmer)

    assert total == 201, f"total={total}, erwartet 201"
    assert len(ids) == 201, "ueber Seiten muessen alle 201 ankommen"
    assert set(ids) == set(eigene)

    # Und die Gegenprobe zum alten Verhalten: **eine** Seite traegt nur 100.
    # Genau diese Seite hat die alte Oberflaeche fuer die ganze Liste
    # genommen — ohne total konnte sie den Unterschied nicht kennen.
    erste = await _belegungs_seite(client, limit=100, offset=0, room_id=zimmer)
    assert len(erste["items"]) == 100
    assert erste["total"] == 201
    assert erste["limit"] == 100
    assert erste["offset"] == 0


async def test_total_gehoert_zu_denselben_filtern_wie_die_seite(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """``total`` zaehlt mit den Filtern der Anfrage, nicht die ganze Tabelle.

    Das ist die Zusicherung, die „N von M" erst richtig macht. Zaehlte
    ``total`` ohne Filter, wuerde die Oberflaeche im Bereich „Heute"
    „12 von 959" anzeigen und einen Knopf „Weitere laden" zeigen, der
    nichts mehr holt.

    Geprueft an zwei Achsen: ``room_id`` (zwei eigene Zimmer mit
    unterschiedlich vielen Belegungen) und ``active`` (eine storniert).
    """
    rt = await _seed_room_type(engine, suffix=uuid.uuid4().hex[:8])
    a, b = await _seed_rooms(engine, 2, room_type_id=rt)
    await _seed_occupancies(engine, 7, room_id=a)
    await _seed_occupancies(engine, 3, room_id=b)

    seite_a = await _belegungs_seite(client, limit=100, offset=0, room_id=a)
    seite_b = await _belegungs_seite(client, limit=100, offset=0, room_id=b)
    assert seite_a["total"] == 7
    assert seite_b["total"] == 3

    # --- zweite Achse: eine der sieben stornieren.
    storno_id = int(seite_a["items"][0]["id"])
    resp = await client.patch(f"/api/v1/occupancies/{storno_id}", json={"cancel": True})
    assert resp.status_code == 200, resp.text

    aktiv = await _belegungs_seite(client, limit=100, offset=0, room_id=a, active="true")
    storniert = await _belegungs_seite(client, limit=100, offset=0, room_id=a, active="false")
    assert aktiv["total"] == 6
    assert storniert["total"] == 1
    assert len(aktiv["items"]) == 6
    assert len(storniert["items"]) == 1


# ---------------------------------------------------------------------------
# 3. Die Sortierung muss eindeutig sein — der Test, der ohne T1 rot ist
# ---------------------------------------------------------------------------


async def test_sortierung_traegt_auch_bei_identischem_check_in(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """250 Belegungen mit **demselben** ``check_in``, ueber Seiten gelesen.

    **Das ist der Test, der ohne den Fix rot ist.** Vorher stand im
    Endpoint ``order_by(Occupancy.check_in)`` allein. ``check_in`` ist
    nicht eindeutig — an einem Anreisetag haben bei 45 Zimmern Dutzende
    Buchungen denselben Wert, und hier haben es alle 250. Postgres gibt
    bei gleichem Sortierschluessel **keine** garantierte Reihenfolge:
    zwischen zwei Seitenabrufen kann dieselbe Zeile zweimal erscheinen und
    eine andere gar nicht.

    Solange die Oberflaeche eine einzige Seite geholt hat, war das
    unsichtbar. Mit „Weitere laden" wird es sichtbar — und zwar als
    scheinbar sprunghafte Liste, die niemand einem Sortierschluessel
    zuordnet.

    Geprueft wird deshalb genau das, was dabei kaputtgeht: **keine
    Dopplung und keine Luecke** ueber drei Seitenuebergaenge. Dass der Test
    mit der alten Sortierung zuverlaessig rot ist, laesst sich nicht
    garantieren — eine undefinierte Reihenfolge darf zufaellig auch stabil
    sein. Er ist der Grund, warum die Ordnung total sein **muss**, und die
    Gegenprobe dazu steht im PR-Text.
    """
    rt = await _seed_room_type(engine, suffix=uuid.uuid4().hex[:8])
    (zimmer,) = await _seed_rooms(engine, 1, room_type_id=rt)
    eigene = await _seed_occupancies(engine, 250, room_id=zimmer, gleicher_check_in=True)

    ids, total = await _alle_belegungen(client, seitengroesse=60, room_id=zimmer)

    assert total == 250
    assert len(ids) == len(set(ids)), "eine Belegung doppelt -> Ordnung nicht total"
    assert set(ids) == set(eigene), "eine Belegung fehlt -> Ordnung nicht total"
    # Bei identischem check_in ist id der entscheidende Schluessel; die
    # Reihenfolge muss ihm folgen.
    assert ids == sorted(ids)


async def test_beide_richtungen_sind_vollstaendig_und_spiegelbildlich(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """``order=desc`` liefert dieselbe Menge, genau umgekehrt.

    ``desc`` ist die Richtung, die die Oberflaeche im Bereich „Alle"
    anfragt (juengste zuerst). Dass sie dieselbe Menge liefert, ist nicht
    selbstverstaendlich: eine Sortierung, die nur in einer Richtung total
    ist, verliert in der anderen Zeilen zwischen den Seiten.

    Die Vorgabe bleibt ``asc`` — der Test haelt das mit fest, weil ein
    stiller Wechsel des Defaults jedem anderen Aufrufer die Reihenfolge
    unter den Fuessen wegzieht.
    """
    rt = await _seed_room_type(engine, suffix=uuid.uuid4().hex[:8])
    (zimmer,) = await _seed_rooms(engine, 1, room_type_id=rt)
    await _seed_occupancies(engine, 120, room_id=zimmer, gleicher_check_in=True)

    auf, total_auf = await _alle_belegungen(client, seitengroesse=50, room_id=zimmer, order="asc")
    ab, total_ab = await _alle_belegungen(client, seitengroesse=50, room_id=zimmer, order="desc")

    assert total_auf == total_ab == 120
    assert len(ab) == len(set(ab)), "desc doppelt eine Zeile"
    assert ab == list(reversed(auf))

    # Vorgabe ohne ``order`` ist aufsteigend.
    ohne, _ = await _alle_belegungen(client, seitengroesse=50, room_id=zimmer)
    assert ohne == auf
