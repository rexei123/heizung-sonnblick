"""Sprint 20c (B-20c-1) — die Geraeteliste darf nicht still abschneiden.

**Der Befund, am 01.10.2026 auf dem Server belegt:** `device` hatte 104
Zeilen, die Oberflaeche zeigte 100. Gefehlt haben die vier mit den
hoechsten IDs — und das sind die zuletzt eingepairten, also genau die, die
bei der Montage gebraucht werden.

Die Ursache ist kein Fehler im Endpoint: ``GET /api/v1/devices`` ist
paginiert, liefert ohne ``limit`` 100 Zeilen (``api/v1/devices.py:247``) und
sortiert nach ``id`` aufsteigend (``device_service.py:108``). Der Fehler lag
darin, dass **fuenf** Aufrufer im Frontend die vollstaendige Liste erwarten
und keiner ein ``limit`` gesetzt hat. Es gab keine Fehlermeldung — die Liste
sah vollstaendig aus.

Was dieser Test festhaelt, in dieser Reihenfolge:

1. Der Default **ist** 100. Das ist die Eigenschaft, gegen die der Client
   paginieren muss; wer sie aendert, soll es hier sehen.
2. Ueber Seiten gelesen kommt **jedes** Geraet genau einmal zurueck —
   keine Luecke, keine Dopplung. Das ist die Zusicherung, auf der die
   Client-Schleife aufsitzt, und sie haengt an der serverseitigen
   Sortierung auf einem eindeutigen Schluessel.
3. Die Grenzfaelle "Seite genau so gross wie der Bestand" und "einer
   mehr als die Seite" — siehe den Docstring dort, warum sie relativ und
   nicht gegen die Literale 100/101 formuliert sind.
4. Die Dashboard-Zaehler sehen alle Geraete. Sie gehen nicht ueber den
   Endpoint, sondern direkt an die Datenbank — das war nie betroffen, und
   dieser Test haelt es fest, damit niemand sie "vorsichtshalber" auf den
   paginierten Pfad umbaut.

**Leftover-fest (§5.39).** Die Test-Datenbank enthaelt Geraete aus anderen
Test-Dateien — ``test_battery_voltage_db`` legt allein 104 fuer seinen
Performance-Beleg an. Keine Zusicherung hier rechnet deshalb mit einer
absoluten Gesamtzahl; jede rechnet mit **eigenen IDs** oder mit dem vorher
gemessenen Ist-Bestand. Dazu raeumt eine Fixture die eigenen Zeilen nach
jedem Test weg, damit die Datei den Rest der Suite nicht aufblaeht.

Folgt der DB-Skip-Konvention von ``test_api_devices_cross_sicht``: skip
lokal ohne ``DATABASE_URL`` (§5.50 — lokal mit Postgres laufen lassen, nicht
nur skippen; hier nicht moeglich, B-18-5).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

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
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.services import dashboard_aggregates as agg

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"

# Der Server-Default des Endpoints (``api/v1/devices.py:247``). Steht hier als
# Konstante, damit nicht drei Tests dieselbe 100 von Hand tragen.
DEFAULT_LIMIT = 100

# Die Obergrenze, die der Endpoint fuer ``limit`` zulaesst. Begrenzt, wie
# gross eine Seite in den Grenzfall-Tests werden darf.
MAX_LIMIT = 1000

# IDs, die diese Datei angelegt hat — fuer das Aufraeumen nach jedem Test.
_angelegt: list[int] = []


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
    """Loescht nach jedem Test die Geraete, die dieser Test angelegt hat.

    Ohne das haette der zweite Test dieser Datei die 105 Zeilen des ersten
    im Bestand — und die Grenzfall-Tests waeren von der Reihenfolge
    abhaengig. Geloescht wird nur nach **eigenen IDs** (§5.39); die Zeilen
    haben keine Kind-Rows (kein Reading, kein Command), ein einfaches
    ``DELETE`` genuegt.

    Der Test committed, ein Rollback greift also nicht.
    """
    _angelegt.clear()
    try:
        yield
    finally:
        if _angelegt:
            sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
            async with sessionmaker() as session:
                await session.execute(delete(Device).where(Device.id.in_(list(_angelegt))))
                await session.commit()
            _angelegt.clear()


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


async def _seed_devices(engine: AsyncEngine, anzahl: int) -> list[int]:
    """Legt ``anzahl`` aktive Pool-Geraete an und gibt ihre IDs zurueck.

    Pool-Geraete (``heating_zone_id IS NULL``) ohne Zone und ohne Reading —
    genau der Zustand nach dem Einpairen und vor der Montage, also der, in
    dem der Befund aufgetreten ist.

    schema_constraint: ``device.dev_eui`` max 16 chars. Aufbau ist
    8 Hex-Zeichen Lauf-Suffix + 8 Stellen Zaehler = **genau 16** (§5.18/§5.49).
    ``hardware_number`` bleibt ``None``: der Unique-Index darauf ist partiell
    (``WHERE hardware_number IS NOT NULL``), beliebig viele NULL sind erlaubt.
    """
    suffix = uuid.uuid4().hex[:8]
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        geraete = [
            Device(
                dev_eui=f"{suffix}{i:08d}",
                kind=DeviceKind.THERMOSTAT,
                vendor=DeviceVendor.MCLIMATE,
                model="vicki",
                health_state="healthy",
            )
            for i in range(anzahl)
        ]
        session.add_all(geraete)
        await session.commit()
        ids = [int(g.id) for g in geraete]
    _angelegt.extend(ids)
    return ids


async def _seite(
    client: httpx.AsyncClient, *, limit: int | None = None, offset: int = 0
) -> list[dict[str, object]]:
    """Eine Seite der Liste. ``limit=None`` laesst den Server-Default greifen."""
    params: dict[str, int] = {"offset": offset}
    if limit is not None:
        params["limit"] = limit
    resp = await client.get("/api/v1/devices", params=params)
    assert resp.status_code == 200, resp.text
    daten = resp.json()
    assert isinstance(daten, list)
    return daten


async def _alle_seiten(client: httpx.AsyncClient, *, seitengroesse: int) -> list[int]:
    """IDs ueber alle Seiten — dieselbe Schleife wie ``devicesApi.list``.

    Bewusst nachgebaut und nicht nur "eine grosse Seite geholt": geprueft
    werden soll, dass die Paginierung **als Verfahren** vollstaendig ist,
    nicht dass ein grosses ``limit`` zufaellig reicht.
    """
    ids: list[int] = []
    offset = 0
    while True:
        teil = await _seite(client, limit=seitengroesse, offset=offset)
        ids.extend(int(d["id"]) for d in teil)
        if len(teil) < seitengroesse:
            return ids
        offset += seitengroesse


# ---------------------------------------------------------------------------
# 1. Die Ursache, als Zusicherung
# ---------------------------------------------------------------------------


async def test_ohne_limit_liefert_der_endpoint_hoechstens_100(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Der Server-Default ist 100 — das ist der Grund fuer die Client-Schleife.

    Das ist **kein** Fehler des Endpoints: ein paginierter Endpoint soll eine
    Seite liefern. Der Fehler lag darin, dass die Oberflaeche diese Seite
    fuer die ganze Liste genommen hat.

    Wer den Default hier aendert, aendert die Annahme, auf der
    ``frontend/src/lib/api/devices.ts`` aufsitzt — und sieht es an diesem
    Test.
    """
    await _seed_devices(engine, 105)

    ohne_limit = await _seite(client)

    assert len(ohne_limit) == DEFAULT_LIMIT
    # Und die Gegenprobe: es gibt mehr. Die Liste war also abgeschnitten,
    # ohne dass die Antwort das sagt — kein Gesamtzaehler, kein next-Link,
    # kein Hinweis. Genau deshalb muss der Client paginieren.
    assert len(await _alle_seiten(client, seitengroesse=MAX_LIMIT)) > DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# 2. Vollstaendigkeit ueber Seiten
# ---------------------------------------------------------------------------


async def test_105_geraete_kommen_ueber_seiten_vollstaendig_zurueck(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Jedes der 105 Geraete genau einmal — keine Luecke, keine Dopplung.

    Das ist die Zusicherung, auf der die Client-Schleife aufsitzt. Sie haengt
    daran, dass die Sortierung **serverseitig** und auf einem eindeutigen
    Schluessel liegt (``order_by(Device.id)``). Bei einer Sortierung nach
    einem mehrfach vorkommenden Wert — etwa ``label``, das die Oberflaeche
    anzeigt — koennte zwischen zwei Seiten eine Zeile doppelt oder gar nicht
    erscheinen.

    Absichtlich mit kleinen Seiten (25): 105 eigene Geraete plus Bestand sind
    so mindestens fuenf Seiten, also vier Uebergaenge, an denen etwas
    verloren gehen koennte. Mit einer Seite von 500 waere die Schleife nie
    gelaufen.
    """
    eigene = await _seed_devices(engine, 105)

    alle = await _alle_seiten(client, seitengroesse=25)

    assert len(alle) == len(set(alle)), "eine ID doppelt -> Sortierung nicht eindeutig"
    fehlende = set(eigene) - set(alle)
    assert not fehlende, f"{len(fehlende)} Geraete fehlen in der paginierten Liste"


async def test_sortierung_ist_aufsteigend_nach_id(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    """Stabile Ordnung — sonst traegt die Paginierung nicht.

    Erwartungswert aus der Definition in ``device_service.py:108``, nicht aus
    einem Lauf (§5.79).
    """
    await _seed_devices(engine, 105)

    alle = await _alle_seiten(client, seitengroesse=25)

    assert alle == sorted(alle)


# ---------------------------------------------------------------------------
# 3. Die Grenzfaelle an der Seitengroesse
# ---------------------------------------------------------------------------


async def test_volle_seite_und_einer_mehr(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    """Der Auftrag nennt "genau 100 / 101" — hier steht er relativ.

    Gemeint ist die Stelle, an der die Abbruchbedingung der Client-Schleife
    entscheidet: **eine Seite kommt voll zurueck.** Dann ist offen, ob es
    weitergeht, und nur ein weiterer Aufruf klaert das. Genau diesen Fall
    hat die alte Oberflaeche falsch beantwortet — sie hat "voll" als
    "fertig" gelesen.

    Warum nicht gegen die Literale 100 und 101: der Endpoint liefert **alle**
    Geraete der Datenbank, und dort liegen Zeilen aus anderen Test-Dateien
    (``test_battery_voltage_db`` legt 104 an). Ein Test, der 100 als
    Gesamtzahl behauptet, haengt damit an der Ausfuehrungsreihenfolge der
    Suite — er wuerde heute gruen sein und beim naechsten neuen DB-Test
    kippen, ohne dass sich am Verhalten etwas geaendert hat.

    Stattdessen wird die Seitengroesse an den Ist-Bestand gelegt. Das prueft
    dieselbe Eigenschaft und ist von Leftovers unabhaengig (§5.39). Die
    Literale 100/101 stehen im e2e-Test, wo die Zahlen kontrolliert sind.
    """
    await _seed_devices(engine, 105)

    gesamt = len(await _alle_seiten(client, seitengroesse=MAX_LIMIT))
    assert gesamt >= 105
    assert gesamt <= MAX_LIMIT, (
        f"Bestand {gesamt} ueber der limit-Obergrenze {MAX_LIMIT} — dieser Test "
        "kann die Seite dann nicht mehr auf den Bestand legen."
    )

    # --- Seite genau so gross wie der Bestand: voll, und die naechste leer.
    erste = await _seite(client, limit=gesamt, offset=0)
    zweite = await _seite(client, limit=gesamt, offset=gesamt)
    assert len(erste) == gesamt, "erste Seite muss den ganzen Bestand tragen"
    assert zweite == [], "hinter einer genau passenden Seite kommt nichts mehr"

    # --- Seite um eins kleiner: voll, und die naechste traegt genau einen.
    # Das ist der Fall "101 bei Seitengroesse 100" aus dem Auftrag.
    erste = await _seite(client, limit=gesamt - 1, offset=0)
    zweite = await _seite(client, limit=gesamt - 1, offset=gesamt - 1)
    assert len(erste) == gesamt - 1
    assert len(zweite) == 1, "der letzte Eintrag darf nicht verloren gehen"

    # Und die Schleife selbst kommt in beiden Faellen auf denselben Bestand.
    assert len(await _alle_seiten(client, seitengroesse=gesamt)) == gesamt
    assert len(await _alle_seiten(client, seitengroesse=gesamt - 1)) == gesamt


# ---------------------------------------------------------------------------
# 4. Die Zaehler gehen nicht ueber den Endpoint
# ---------------------------------------------------------------------------


async def test_dashboard_zaehler_sehen_alle_105(engine: AsyncEngine) -> None:
    """Die Kacheln zaehlen in der Datenbank, nicht in einer Seite.

    ``count_devices_online`` und ``count_battery_low`` lesen direkt
    (``dashboard_aggregates.py:59`` und ``:199``) und waren vom Befund
    **nicht** betroffen. Dieser Test haelt das fest — damit niemand sie bei
    einer spaeteren Umstellung "vereinheitlicht" und dabei auf den
    paginierten Pfad legt.

    Geprueft wird die Differenz, nicht die Gesamtzahl: in der Datenbank
    liegen Geraete aus anderen Tests (§5.39).
    """
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        _, total_vorher = await agg.count_devices_online(session)

    await _seed_devices(engine, 105)

    async with sessionmaker() as session:
        _, total_nachher = await agg.count_devices_online(session)

    assert total_nachher - total_vorher == 105
