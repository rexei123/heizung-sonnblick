"""POST /api/v1/rooms/{id}/boost — die sechs Gruende und der gute Fall.

**Was dieser Endpunkt anders macht als die Uebersteuerung:** er hat
keinen Rumpf. Wert und Ende rechnet ``services/boost``; die Rezeption
waehlt nichts aus. Entsprechend prueft diese Datei nicht Eingaben,
sondern **Lagen**.

Die Reihenfolge der Gruende ist Teil der Zusicherung: der Mensch bekommt
genau einen Satz zu sehen, und es soll der richtige sein. Zwei Tests
halten deshalb ausdruecklich einen Vorrang fest.

DB-Skip-Konvention wie ``test_api_overrides`` (§5.50). Suffixe aus
``uuid4`` und nicht aus der Uhr (§5.59).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from heizung.auth.dependencies import get_current_user
from heizung.db import get_session
from heizung.main import app
from heizung.models.enums import RuleConfigScope, UserRole
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"

#: Das Nachtfenster des Hauses.
NACHT = (time(22, 0), time(6, 0))


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
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

    def _override_user() -> User:
        return User(
            id=1,
            email="rezeption@hotel.example.com",
            role=UserRole.MITARBEITER,
            is_active=True,
        )

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_current_user] = _override_user
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class Aufbau:
    def __init__(self, room_id: int, rt_id: int) -> None:
        self.room_id = room_id
        self.rt_id = rt_id


@asynccontextmanager
async def _zimmer(
    engine: AsyncEngine,
    *,
    buchbar: bool = True,
    belegt: bool = False,
    gesperrt: bool = False,
    bis_checkout: bool = False,
    nacht: tuple[time, time] | None = NACHT,
    boost_wert: str | None = "24.0",
    guest_max: str | None = None,
) -> AsyncIterator[Aufbau]:
    """Ein Zimmer mit genau der Lage, die der jeweilige Test braucht.

    **Kontextmanager und nicht ``async for``** (Berichtigung vom
    02.11.2026). Die erste Fassung war ein nackter Generator, und die
    Tests liefen ihn mit ``async for ... in _zimmer(...)``. Das raeumt
    nur auf, wenn der Generator auch beendet wird — bei vier von neun
    Zimmern geschah das nicht, und sie blieben samt ihrer
    ``rule_config``-Zeile in der Test-Datenbank stehen.

    Aufgefallen ist es in einer **anderen** Datei:
    ``test_allgemeinbereiche::test_hausstandard_nutzung_zaehlt_eigene_werte``
    zaehlt ROOM-Zeilen mit ``night_start`` und erwartet 0 — es waren 4.
    Genau das Fehlerbild aus Paragraph 5.39, und genau die Begruendung
    fuer die zwei Schichten dort: ein Kontextmanager raeumt deterministisch
    (``async with``), und der Praefix-Putz unten faengt ab, was ein
    Abbruch mitten im Test liegen laesst.

    Die Regelwerte kommen als **ROOM**-Zeile. Das ist der Rang, der jeden
    anderen schlaegt, und damit haengt kein Test an einer hausweiten
    Zeile, die ein anderer Test gesetzt haben koennte (§5.39).
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    kurz = uuid.uuid4().hex[:8]
    jetzt = datetime.now(tz=UTC)

    async with maker() as session:
        rt = RoomType(
            name=f"boost-{kurz}",
            is_bookable=buchbar,
            default_t_occupied=Decimal("21.0"),
            default_t_vacant=Decimal("17.0"),
        )
        session.add(rt)
        await session.flush()

        room = Room(
            number=f"bo-{kurz}",
            room_type_id=rt.id,
            guest_override_blocked=gesperrt,
            guest_block_bis_checkout=bis_checkout,
        )
        session.add(room)
        await session.flush()

        if nacht is not None or boost_wert is not None or guest_max is not None:
            session.add(
                RuleConfig(
                    scope=RuleConfigScope.ROOM,
                    room_id=room.id,
                    night_start=nacht[0] if nacht else None,
                    night_end=nacht[1] if nacht else None,
                    boost_temperature=Decimal(boost_wert) if boost_wert else None,
                    guest_override_max=Decimal(guest_max) if guest_max else None,
                )
            )

        if belegt:
            session.add(
                Occupancy(
                    room_id=room.id,
                    check_in=jetzt - timedelta(hours=2),
                    check_out=jetzt + timedelta(days=2),
                    is_active=True,
                )
            )
        await session.commit()
        ids = Aufbau(room.id, rt.id)

    try:
        yield ids
    finally:
        async with maker() as session:
            for tabelle in ("manual_override", "occupancy", "rule_config", "event_log"):
                spalte = "room_id"
                await session.execute(
                    text(f"DELETE FROM {tabelle} WHERE {spalte} = :r"), {"r": ids.room_id}
                )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            await session.execute(text("DELETE FROM room_type WHERE id = :r"), {"r": ids.rt_id})
            await session.commit()


@pytest_asyncio.fixture
async def freies_zimmer(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    async with _zimmer(setup_engine) as a:
        yield a


@pytest_asyncio.fixture
async def belegtes_zimmer(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    async with _zimmer(setup_engine, belegt=True) as a:
        yield a


@pytest_asyncio.fixture(autouse=True)
async def _putz(setup_engine: AsyncEngine) -> AsyncIterator[None]:
    """Zweite Schicht gegen Reste (Paragraph 5.39).

    Der Kontextmanager raeumt deterministisch — solange der Test ihn
    verlaesst. Ein Abbruch mitten im ``async with`` (``KeyboardInterrupt``,
    ein harter Fehler im Teardown) laesst trotzdem etwas liegen, und was
    hier liegen bleibt, faellt in einer **anderen** Datei auf: am
    02.11.2026 waren es vier ROOM-Zeilen mit ``night_start``, und rot
    wurde ``test_allgemeinbereiche``.

    Geraeumt wird vor **und** nach jedem Test, ueber den Praefix. Vorher,
    weil ein Rest aus einem abgebrochenen Lauf sonst den naechsten
    begleitet.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _weg() -> None:
        async with maker() as session:
            for tabelle in ("manual_override", "occupancy", "rule_config", "event_log"):
                await session.execute(
                    text(
                        f"DELETE FROM {tabelle} WHERE room_id IN "
                        "(SELECT id FROM room WHERE number LIKE 'bo-%')"
                    )
                )
            await session.execute(text("DELETE FROM room WHERE number LIKE 'bo-%'"))
            await session.execute(text("DELETE FROM room_type WHERE name LIKE 'boost-%'"))
            await session.commit()

    await _weg()
    yield
    await _weg()


@pytest_asyncio.fixture(autouse=True)
def _kein_celery(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """``_evaluate_room_task.delay`` schreibt sonst in die echte Queue."""
    from heizung.api.v1 import overrides as overrides_api

    gerufen: list[int] = []
    monkeypatch.setattr(overrides_api._evaluate_room_task, "delay", lambda rid: gerufen.append(rid))
    return gerufen


# ---------------------------------------------------------------------------
# Der gute Fall
# ---------------------------------------------------------------------------


async def test_boost_im_freien_zimmer(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau
) -> None:
    """**Festlegung 2 des Betreibers: eine Regel fuer belegt und frei.**

    Eine gewoehnliche Uebersteuerung weist ein freies Zimmer ab (AE-58).
    Der Boost nicht — der haeufige Fall ist ein Zimmer, das in einer
    Stunde bezogen wird und jetzt kalt ist.
    """
    antwort = await http_client.post(f"/api/v1/rooms/{freies_zimmer.room_id}/boost")

    assert antwort.status_code == 201, antwort.text
    koerper = antwort.json()
    assert Decimal(str(koerper["setpoint"])) == Decimal("24.0")
    assert koerper["source"] == "frontend_boost"


async def test_boost_im_belegten_zimmer(
    http_client: httpx.AsyncClient, belegtes_zimmer: Aufbau
) -> None:
    antwort = await http_client.post(f"/api/v1/rooms/{belegtes_zimmer.room_id}/boost")
    assert antwort.status_code == 201, antwort.text


async def test_das_ende_ist_der_naechste_nachtfenster_wechsel(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau
) -> None:
    """Das Ende liegt in der Zukunft und hoechstens eine Nacht entfernt.

    Der genaue Zeitpunkt haengt an der Uhr des Laufs und steht in
    ``test_boost.py`` als reine Funktion. Hier wird gepruef, dass der
    Endpunkt ihn **benutzt** — ein Ende von ``now + 24 h`` waere die
    naheliegende Verwechslung mit ``frontend_24h`` und faellt hier auf.
    """
    jetzt = datetime.now(tz=UTC)
    antwort = await http_client.post(f"/api/v1/rooms/{freies_zimmer.room_id}/boost")

    assert antwort.status_code == 201, antwort.text
    ende = datetime.fromisoformat(antwort.json()["expires_at"])
    assert jetzt < ende <= jetzt + timedelta(hours=24)


async def test_der_boost_loest_eine_auswertung_aus(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau, _kein_celery: list[int]
) -> None:
    """Wie bei der Uebersteuerung: Layer 3 soll sofort greifen (AE-07)."""
    await http_client.post(f"/api/v1/rooms/{freies_zimmer.room_id}/boost")
    assert _kein_celery == [freies_zimmer.room_id]


async def test_ohne_boostwert_gilt_der_hoechstwert_des_gastes(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """**Warum es diesen Rueckfall gibt.**

    ``boost_temperature`` ist nach der Migration ueberall ``NULL``. Ohne
    Rueckfall waere die Funktion am Tag des Einbaus tot — und der
    Betreiber muesste erst eine Zahl eintragen, die ihm niemand genannt
    hat. Der Hoechstwert, den die Rezeption ohnehin eingeben darf, ist
    die Zahl, die schon im Haus steht.
    """
    async with _zimmer(setup_engine, boost_wert=None, guest_max="23.0") as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 201, antwort.text
        assert Decimal(str(antwort.json()["setpoint"])) == Decimal("23.0")


async def test_ein_boost_darf_einen_laufenden_boost_ersetzen(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau
) -> None:
    """Sonst waere der Knopf nach dem ersten Druck bis zur Nacht tot.

    Der zweite Boost endet am selben Zeitpunkt; der Stapel-Abbau in
    ``override_service.create`` raeumt den ersten weg.
    """
    erste = await http_client.post(f"/api/v1/rooms/{freies_zimmer.room_id}/boost")
    zweite = await http_client.post(f"/api/v1/rooms/{freies_zimmer.room_id}/boost")

    assert erste.status_code == 201, erste.text
    assert zweite.status_code == 201, zweite.text
    assert zweite.json()["id"] != erste.json()["id"]


# ---------------------------------------------------------------------------
# Die Gruende, in ihrer Reihenfolge
# ---------------------------------------------------------------------------


async def test_dauerhafte_sperre_weist_ab(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    async with _zimmer(setup_engine, gesperrt=True) as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 409, antwort.text
        assert antwort.json()["grund"] == "dauerhaft_gesperrt"
        assert antwort.json()["detail"] == "Dauerhaft gesperrt"


async def test_sperre_bis_checkout_laesst_den_boost_durch(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Die Sperre „bis Check-out" trifft das Rad des Gastes, nicht das Personal.

    Dieselbe Unterscheidung wie bei jeder ``frontend_*``-Quelle
    (Sprint 23 T4-A2). Ohne diesen Test waere der Boost die eine Quelle,
    die sie nicht kennt.
    """
    async with _zimmer(setup_engine, belegt=True, gesperrt=True, bis_checkout=True) as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 201, antwort.text


async def test_allgemeinbereich_weist_ab_und_nennt_den_anderen_weg(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Der Satz nennt den Weg, der dort gilt — nicht nur das Verbot."""
    async with _zimmer(setup_engine, buchbar=False) as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 409, antwort.text
        assert antwort.json()["grund"] == "allgemeinbereich"
        assert "Zimmerseite" in antwort.json()["detail"]


async def test_ohne_nachtfenster_wird_abgewiesen(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """**Festlegung 3: keine erfundene Dauer.**

    Ohne Nachtfenster gibt es kein Ende, und ein Boost ohne Ende waere
    eine dauerhafte Uebersteuerung — genau das, was die Funktion nicht
    sein soll.
    """
    async with _zimmer(setup_engine, nacht=None) as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 409, antwort.text
        assert antwort.json()["grund"] == "kein_nachtfenster"


async def test_nachtfenster_ohne_ausdehnung_wird_abgewiesen(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """``night_start == night_end`` hat keinen Wechsel.

    Ohne diesen Zweig liefe die Rechnung in ein Ende **morgen zur
    selben Uhrzeit** — ein Boost von 24 Stunden, und zwar fuer eine
    Konfiguration, die aus der Sicht des Lesers gar keine ist.
    """
    async with _zimmer(setup_engine, nacht=(time(22, 0), time(22, 0))) as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 409, antwort.text
        assert antwort.json()["grund"] == "kein_nachtfenster"


async def test_ohne_jeden_wert_wird_abgewiesen(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    async with _zimmer(setup_engine, boost_wert=None, guest_max=None) as a:
        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 409, antwort.text
        assert antwort.json()["grund"] == "kein_boostwert"


async def test_eine_laufende_uebersteuerung_weist_den_boost_ab(
    http_client: httpx.AsyncClient, belegtes_zimmer: Aufbau
) -> None:
    """**Festlegung 1, Variante (c).**

    Weder „Boost ersetzt sie" noch „Boost legt sich darueber": abweisen
    mit Grund. Der Satz steht woertlich so in der Festlegung vom
    31.10.2026, weil er der Rezeption sagt, **wo** sie den Wert aendert.
    """
    gesetzt = await http_client.post(
        f"/api/v1/rooms/{belegtes_zimmer.room_id}/overrides",
        json={"setpoint": "23", "source": "frontend_24h"},
    )
    assert gesetzt.status_code == 201, gesetzt.text

    antwort = await http_client.post(f"/api/v1/rooms/{belegtes_zimmer.room_id}/boost")

    assert antwort.status_code == 409, antwort.text
    koerper = antwort.json()
    assert koerper["grund"] == "uebersteuerung_aktiv"
    assert koerper["detail"].startswith("Übersteuerung aktiv (23 °C bis ")
    assert koerper["detail"].endswith(") – Wert dort ändern")


async def test_die_sperre_schlaegt_die_laufende_uebersteuerung(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Die Reihenfolge der Gruende ist Teil der Zusicherung.

    Ein dauerhaft gesperrtes Zimmer mit laufender Uebersteuerung soll
    „Dauerhaft gesperrt" melden und nicht „Wert dort aendern" — der
    zweite Satz schickte die Rezeption an eine Stelle, an der sie nichts
    aendern kann.
    """
    async with _zimmer(setup_engine, belegt=True, gesperrt=True, bis_checkout=True) as a:
        gesetzt = await http_client.post(
            f"/api/v1/rooms/{a.room_id}/overrides",
            json={"setpoint": "23", "source": "frontend_24h"},
        )
        assert gesetzt.status_code == 201, gesetzt.text

        # Jetzt die Sperre auf dauerhaft stellen.
        maker = async_sessionmaker(setup_engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(
                text("UPDATE room SET guest_block_bis_checkout = false WHERE id = :r"),
                {"r": a.room_id},
            )
            await session.commit()

        antwort = await http_client.post(f"/api/v1/rooms/{a.room_id}/boost")
        assert antwort.status_code == 409, antwort.text
        assert antwort.json()["grund"] == "dauerhaft_gesperrt"


async def test_unbekanntes_zimmer_ist_404(http_client: httpx.AsyncClient) -> None:
    antwort = await http_client.post("/api/v1/rooms/999999/boost")
    assert antwort.status_code == 404, antwort.text


async def test_ein_rumpf_wird_ignoriert(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau
) -> None:
    """**Der Wert kommt vom Server, nicht vom Aufrufer.**

    Wer einen Sollwert mitschickt, bekommt trotzdem den konfigurierten
    Boost-Wert. Das ist der Grund fuer einen eigenen Endpunkt ohne
    Rumpf: ein Feld, das man setzen kann, wird irgendwann gesetzt.
    """
    antwort = await http_client.post(
        f"/api/v1/rooms/{freies_zimmer.room_id}/boost",
        json={"setpoint": "30", "source": "frontend_24h"},
    )
    assert antwort.status_code == 201, antwort.text
    assert Decimal(str(antwort.json()["setpoint"])) == Decimal("24.0")


async def test_sommermodus_weist_ab(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Im Sommermodus heizt nichts — jeder andere Grund waere Beiwerk.

    Der Sommermodus haengt an ``scenario_assignment`` (AE-49); hier wird
    der Helfer ersetzt, damit der Test nicht eine zweite Mechanik
    aufbaut, die mit dem Boost nichts zu tun hat.
    """
    from heizung.services import boost as boost_service

    async def _aktiv(_session: Any) -> bool:
        return True

    monkeypatch.setattr(boost_service, "is_summer_mode_active", _aktiv)

    antwort = await http_client.post(f"/api/v1/rooms/{freies_zimmer.room_id}/boost")

    assert antwort.status_code == 409, antwort.text
    assert antwort.json()["grund"] == "sommermodus"
    assert antwort.json()["detail"] == "Sommermodus aktiv"


# ---------------------------------------------------------------------------
# Die Liste sagt, ob ein Boost ginge — und welche Uebersteuerung gilt
# ---------------------------------------------------------------------------


async def _zeile(client: httpx.AsyncClient, room_id: int) -> dict[str, Any]:
    """Die Zeile dieses Zimmers aus dem Listen-Endpunkt."""
    antwort = await client.get("/api/v1/rooms?limit=1000")
    assert antwort.status_code == 200, antwort.text
    treffer = [z for z in antwort.json() if z["id"] == room_id]
    assert treffer, f"Zimmer {room_id} nicht in der Liste"
    return treffer[0]


async def test_die_liste_nennt_das_moegliche_boost_ende(
    http_client: httpx.AsyncClient, freies_zimmer: Aufbau
) -> None:
    """Der Knopf traegt die Endzeit in seiner Beschriftung.

    Ohne dieses Feld muesste die Oberflaeche das Nachtfenster selbst
    kennen und die Rechnung nachbauen — zwei Wahrheiten ueber dieselbe
    Uhrzeit (§5.53).
    """
    zeile = await _zeile(http_client, freies_zimmer.room_id)

    assert zeile["boost_moeglich"] is True
    assert zeile["boost_grund"] is None
    assert zeile["boost_ende"] is not None
    assert datetime.fromisoformat(zeile["boost_ende"]) > datetime.now(tz=UTC)


async def test_die_liste_nennt_den_grund_wenn_kein_boost_geht(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """**Kein Knopf ohne sichtbaren Grund.**

    Der Satz kommt aus dem Backend, weil dort die Schwellen und die
    Regelkette stehen. Die Oberflaeche zeigt ihn als Tooltip und als
    ``sr-only``-Text.
    """
    async with _zimmer(setup_engine, nacht=None) as a:
        zeile = await _zeile(http_client, a.room_id)
        assert zeile["boost_moeglich"] is False
        assert zeile["boost_grund"] == "kein_nachtfenster"
        assert zeile["boost_hinweis"] == "Kein Nachtfenster konfiguriert"
        assert zeile["boost_ende"] is None


async def test_die_liste_nennt_quelle_und_ablauf_der_uebersteuerung(
    http_client: httpx.AsyncClient, belegtes_zimmer: Aufbau
) -> None:
    """``has_active_override`` sagt „eine laeuft" und verschweigt welche.

    Fuer die Kennzeichnung eines Boosts (Flammen-Zeichen, „Boost bis
    HH:MM") braucht die Zeile die Quelle.
    """
    gesetzt = await http_client.post(f"/api/v1/rooms/{belegtes_zimmer.room_id}/boost")
    assert gesetzt.status_code == 201, gesetzt.text

    zeile = await _zeile(http_client, belegtes_zimmer.room_id)

    assert zeile["has_active_override"] is True
    assert zeile["uebersteuerung_quelle"] == "frontend_boost"
    assert zeile["uebersteuerung_ende"] == gesetzt.json()["expires_at"]
    # Ein laufender Boost schliesst den naechsten nicht aus — sonst waere
    # der Knopf nach dem ersten Druck bis zur Nacht tot.
    assert zeile["boost_moeglich"] is True


async def test_eine_laufende_uebersteuerung_sperrt_den_knopf_in_der_liste(
    http_client: httpx.AsyncClient, belegtes_zimmer: Aufbau
) -> None:
    gesetzt = await http_client.post(
        f"/api/v1/rooms/{belegtes_zimmer.room_id}/overrides",
        json={"setpoint": "23", "source": "frontend_24h"},
    )
    assert gesetzt.status_code == 201, gesetzt.text

    zeile = await _zeile(http_client, belegtes_zimmer.room_id)

    assert zeile["boost_moeglich"] is False
    assert zeile["boost_grund"] == "uebersteuerung_aktiv"
    assert zeile["uebersteuerung_quelle"] == "frontend_24h"
