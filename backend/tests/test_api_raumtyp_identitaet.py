"""Ein Update trifft den Raumtyp, zu dem es gehört (Sprint 24e, PR A).

**Der Befund des Betreibers, 25.10.2026.** Auf der Raumtypen-Seite war
links „Raum intern" ausgewählt, und das Bearbeitungsformular darunter
zeigte „Raum mit Exit" samt dessen Werten. Ein Klick auf „Aktualisieren"
hätte die Werte des einen Raumtyps in den anderen geschrieben.

Die Ursache lag in der Oberfläche und ist dort behoben
(`fix-raumtyp-formular.spec.ts`). Diese Datei prüft die **zweite Hälfte**:
der Endpunkt nimmt das Echo der bearbeiteten ID und weist die Anfrage ab,
wenn sie nicht zum Weg passt. Der Server soll sich nicht darauf verlassen,
dass die Oberfläche richtig rechnet.

**Und sie hält fest, was den Schaden tatsächlich verhindert hat.**
`room_type.name` trägt einen Eindeutigkeits-Index. Ein Speichern hätte den
**fremden Namen** mitgesendet, und der Index hätte die ganze Anweisung
abgewiesen — nichts wäre geschrieben worden. Das ist kein Schutz, den
jemand dafür gebaut hat, sondern ein Zufall, der gehalten hat. Genau diese
Sorte Umstand gehört aufgeschrieben, solange man sie noch kennt (§5.78).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.db import get_session
from heizung.main import app
from heizung.models.room_type import RoomType

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"
PREFIX = "t24e"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason=SKIP_REASON)


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
    engine = create_async_engine(DATABASE_URL or "")
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


@pytest_asyncio.fixture
async def zwei_raumtypen(setup_engine: AsyncEngine) -> AsyncIterator[tuple[int, int]]:
    """Zwei Raumtypen mit **verschiedenen** Werten — sonst wäre nicht zu
    sehen, welcher von beiden geschrieben wurde."""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:6]
    async with maker() as session:
        a = RoomType(
            name=f"{PREFIX}-a-{short}",
            is_bookable=False,
            default_t_occupied=Decimal(21),
            default_t_vacant=Decimal(21),
            default_t_night=Decimal(19),
        )
        b = RoomType(
            name=f"{PREFIX}-b-{short}",
            is_bookable=False,
            default_t_occupied=Decimal(19),
            default_t_vacant=Decimal(19),
            default_t_night=Decimal(17),
        )
        session.add_all([a, b])
        await session.commit()
        ids = (a.id, b.id)

    try:
        yield ids
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM rule_config WHERE room_type_id = ANY(:ids)"),
                {"ids": list(ids)},
            )
            await session.execute(
                text("DELETE FROM room_type WHERE id = ANY(:ids)"), {"ids": list(ids)}
            )
            await session.commit()


async def _lies(client: httpx.AsyncClient, rt_id: int) -> dict[str, object]:
    resp = await client.get(f"/api/v1/room-types/{rt_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_passendes_echo_wird_gespeichert(
    http_client: httpx.AsyncClient, zwei_raumtypen: tuple[int, int]
) -> None:
    """Der Normalfall: die Oberfläche sendet die ID, die sie bearbeitet hat."""
    a_id, _ = zwei_raumtypen

    resp = await http_client.patch(
        f"/api/v1/room-types/{a_id}", json={"id": a_id, "default_t_vacant": 22.0}
    )

    assert resp.status_code == 200, resp.text
    assert float(resp.json()["default_t_vacant"]) == 22.0


async def test_fremdes_echo_wird_abgewiesen(
    http_client: httpx.AsyncClient, zwei_raumtypen: tuple[int, int]
) -> None:
    """**Die Sicherung.** Pfad A, Körper trägt die ID von B → 409.

    Und zwar **ohne** zu schreiben: der Test liest beide Datensätze danach
    noch einmal. Eine Anfrage, die mit einem Fehler endet und trotzdem die
    Hälfte geschrieben hat, wäre die schlechtere Variante desselben
    Fehlers.
    """
    a_id, b_id = zwei_raumtypen
    vorher = await _lies(http_client, a_id)

    resp = await http_client.patch(
        f"/api/v1/room-types/{a_id}", json={"id": b_id, "default_t_vacant": 19.0}
    )

    assert resp.status_code == 409, resp.text
    assert "neu laden" in resp.json()["detail"]

    nachher = await _lies(http_client, a_id)
    assert nachher["default_t_vacant"] == vorher["default_t_vacant"]
    assert nachher["name"] == vorher["name"]


async def test_ohne_echo_bleibt_es_beim_alten_verhalten(
    http_client: httpx.AsyncClient, zwei_raumtypen: tuple[int, int]
) -> None:
    """Ein Aufrufer ohne das Feld bekommt keine neue Pflicht.

    Das Echo ist bewusst optional: ein Skript oder ein ``curl``-Aufruf aus
    dem RUNBOOK soll nicht brechen, weil die Oberfläche ein Feld dazubekommen
    hat.
    """
    a_id, _ = zwei_raumtypen

    resp = await http_client.patch(f"/api/v1/room-types/{a_id}", json={"default_t_vacant": 20.0})

    assert resp.status_code == 200, resp.text
    assert float(resp.json()["default_t_vacant"]) == 20.0


async def test_das_echo_allein_ist_keine_aenderung(
    http_client: httpx.AsyncClient, zwei_raumtypen: tuple[int, int]
) -> None:
    """``{"id": …}`` und sonst nichts ist keine Aktualisierung.

    Sonst wäre das Echo ein Feld, mit dem man den Endpunkt zu einer
    leeren Schreiboperation überreden kann — und ``updated_at`` würde
    wandern, ohne dass sich etwas geändert hat.
    """
    a_id, _ = zwei_raumtypen

    resp = await http_client.patch(f"/api/v1/room-types/{a_id}", json={"id": a_id})

    assert resp.status_code == 422, resp.text
    assert "Mindestens ein Feld" in resp.json()["detail"]


async def test_ein_fremder_name_wird_vom_index_abgewiesen(
    http_client: httpx.AsyncClient, zwei_raumtypen: tuple[int, int]
) -> None:
    """**Was den Schaden am 25.10. tatsächlich verhindert hat.**

    Hätte der Betreiber im falsch gefüllten Formular auf „Aktualisieren"
    geklickt, wäre der **fremde Name** mitgegangen — und
    ``room_type.name`` trägt einen Eindeutigkeits-Index. Die ganze
    Anweisung wäre abgewiesen worden, nichts geschrieben.

    Das ist kein Schutz, den jemand dafür gebaut hat. Er hält nur, solange
    der Name der einzige eindeutige Wert ist und solange niemand ihn vor
    dem Speichern korrigiert — wer den Namen anpasst und dann speichert,
    schreibt die fremden Temperaturen durch. Deshalb steht er hier als
    Zufall und nicht als Zusicherung.
    """
    a_id, b_id = zwei_raumtypen
    b = await _lies(http_client, b_id)
    vorher = await _lies(http_client, a_id)

    resp = await http_client.patch(
        f"/api/v1/room-types/{a_id}",
        json={"id": a_id, "name": b["name"], "default_t_vacant": 19.0},
    )

    assert resp.status_code == 409, resp.text
    nachher = await _lies(http_client, a_id)
    assert nachher["default_t_vacant"] == vorher["default_t_vacant"], (
        "die abgewiesene Anweisung hat die Haelfte geschrieben"
    )
