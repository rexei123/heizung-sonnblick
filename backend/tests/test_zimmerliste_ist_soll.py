"""Zimmeruebersicht: Ist und Soll in der Listen-Antwort (15.10.2026).

Prueft den Datenbank-Pfad und die Antwortform:

- ``referenzzonen_pro_zimmer`` ueber mehrere Zimmer in **einer** Abfrage
  (normal / zwei Schlafzimmer / Kinderzimmer / ohne Schlafzimmer).
- ``GET /api/v1/rooms`` liefert ``reference_zone_id``,
  ``mean_temperature_c`` und ``engine_setpoint_c`` **ohne** Abfrage je
  Zimmer.
- Decimal kommt als JSON-**Zahl**, nicht als String (§5.63) — und das
  strukturell am rohen Antwort-Text, nicht an einem geparsten Wert.
- Fehlender Messwert -> ``null`` (die Oberflaeche zeigt dann „–").

Die reine Auswahl-Regel steht in ``test_referenzzone.py`` und laeuft
ohne Datenbank.

DB-Tests; skip ohne ``DATABASE_URL`` (§5.50). Fixture-Aufbau wie
``test_sprint14d_override_visibility.py``; Praefix ``tist-`` fuer das
Aufraeumen, Laengen nach §5.49 (``room.number`` ist ``VARCHAR(20)``:
``tist-`` + 8 Hex + 1 = 14 Zeichen; ``device.dev_eui`` ist
``VARCHAR(16)``: ``beef`` + 8 Hex + 4 = 16 Zeichen exakt).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
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
from heizung.auth.password import hash_password
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.db import get_session
from heizung.main import app
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    RoomStatus,
    UserRole,
)
from heizung.models.event_log import EventLog
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.models.user import User
from heizung.services.referenzzone import referenzzonen_pro_zimmer

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _auth_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_limiter() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


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
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
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

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _login_admin(client: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession]) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"tist-admin-{suffix}@test.example.com"
    pw = "IstSollPassword!1"
    async with sm() as session:
        session.add(
            User(
                email=email,
                password_hash=hash_password(pw),
                role=UserRole.ADMIN,
                is_active=True,
                must_change_password=False,
            )
        )
        await session.commit()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert resp.status_code == 200, resp.text


async def _mk_room(sm: async_sessionmaker[AsyncSession], suffix: str) -> int:
    # schema_constraint: room.number max 20 chars -> "tist-" + 9 = 14
    async with sm() as session:
        rt = RoomType(name=f"tist-rt-{suffix}")
        session.add(rt)
        await session.flush()
        room = Room(number=f"tist-{suffix}", room_type_id=rt.id, status=RoomStatus.OCCUPIED)
        session.add(room)
        await session.flush()
        await session.commit()
        return room.id


async def _mk_zone(sm: async_sessionmaker[AsyncSession], room_id: int, name: str) -> int:
    async with sm() as session:
        zone = HeatingZone(room_id=room_id, kind=HeatingZoneKind.BEDROOM, name=name)
        session.add(zone)
        await session.flush()
        await session.commit()
        return zone.id


async def _mk_device_mit_messwert(
    sm: async_sessionmaker[AsyncSession],
    zone_id: int,
    suffix: str,
    temperatur: Decimal | None,
) -> int:
    """Gesundes, aktives Geraet in der Zone, optional mit Messwert.

    ``health_state='healthy'`` ist Pflicht: ``aggregate_zone_readings``
    zaehlt nur gesunde Geraete (AE-51 §4.1). Mit dem Default ``silent``
    waere das Aggregat ``None``, und der Test wuerde das Fehlen eines
    Messwerts beweisen statt seines Vorhandenseins.
    """
    # schema_constraint: device.dev_eui max 16 chars -> "beef" + 8 + 4 = 16
    async with sm() as session:
        dev = Device(
            dev_eui=f"beef{suffix}0001",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="Vicki",
            heating_zone_id=zone_id,
            health_state="healthy",
        )
        session.add(dev)
        await session.flush()
        device_id = dev.id
        if temperatur is not None:
            session.add(
                SensorReading(
                    time=datetime.now(tz=UTC) - timedelta(minutes=5),
                    device_id=device_id,
                    temperature=temperatur,
                )
            )
        await session.commit()
        return device_id


async def _mk_hard_clamp(
    sm: async_sessionmaker[AsyncSession],
    room_id: int,
    setpoint: Decimal,
    *,
    zonen: dict[int, int] | None = None,
) -> None:
    """Juengste HARD_CLAMP-Zeile des Zimmers — die Quelle des Soll-Werts.

    Der 1-h-Frische-Filter in ``latest_hard_clamp_setpoint_per_room`` ist
    der Grund fuer ``now - 1 min``: eine aeltere Zeile wuerde korrekt
    ignoriert (dafuer gibt es einen eigenen Test weiter unten).

    ``zonen`` schreibt den Zustandsbericht je Zone mit, aus dem die Liste
    seit dem 31.10.2026 den Sollwert der **Referenzzone** nimmt. ``None``
    laesst ihn weg — das ist die Lage einer Zeile aus der Zeit davor, und
    dafuer gibt es den Rueckfall auf den Zimmerwert.
    """
    details: dict[str, object] = {"detail": "test"}
    if zonen is not None:
        details["downlink_zone_status"] = [
            {"zone_id": zid, "setpoint_c": wert, "count_sent": 1} for zid, wert in zonen.items()
        ]
    async with sm() as session:
        session.add(
            EventLog(
                time=datetime.now(tz=UTC) - timedelta(minutes=1),
                room_id=room_id,
                evaluation_id=uuid.uuid4(),
                layer=EventLogLayer.HARD_CLAMP,
                setpoint_in=setpoint,
                setpoint_out=setpoint,
                reason=CommandReason.OCCUPIED_SETPOINT,
                details=details,
            )
        )
        await session.commit()


async def _cleanup(sm: async_sessionmaker[AsyncSession]) -> None:
    async with sm() as session:
        await session.execute(
            text(
                "DELETE FROM sensor_reading WHERE device_id IN "
                "(SELECT id FROM device WHERE dev_eui LIKE 'beef%')"
            )
        )
        await session.execute(text("DELETE FROM device WHERE dev_eui LIKE 'beef%'"))
        await session.execute(
            text(
                "DELETE FROM event_log WHERE room_id IN "
                "(SELECT id FROM room WHERE number LIKE 'tist-%')"
            )
        )
        await session.execute(text("DELETE FROM room WHERE number LIKE 'tist-%'"))
        await session.execute(text("DELETE FROM room_type WHERE name LIKE 'tist-rt-%'"))
        await session.execute(
            text("""DELETE FROM "user" WHERE email LIKE 'tist-admin-%@test.example.com'""")
        )
        await session.commit()


async def test_referenzzonen_pro_zimmer_deckt_die_vier_faelle(
    setup_engine: AsyncEngine,
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        # 1. Normalfall (41 von 45 Zimmern): Schlafzimmer + Bad
        normal = await _mk_room(sm, f"{s}a")
        sz_normal = await _mk_zone(sm, normal, "Schlafzimmer")
        await _mk_zone(sm, normal, "Bad")

        # 2. Suite mit zwei Schlafzimmern (52, 54, 102, 202)
        suite = await _mk_room(sm, f"{s}b")
        sz_rechts = await _mk_zone(sm, suite, "Schlafzimmer R")
        sz_links = await _mk_zone(sm, suite, "Schlafzimmer L")
        await _mk_zone(sm, suite, "Bad")

        # 3. Suite mit Kinderzimmer (9 Zimmer)
        kind = await _mk_room(sm, f"{s}c")
        sz_kind = await _mk_zone(sm, kind, "Schlafzimmer")
        kz = await _mk_zone(sm, kind, "Kinderzimmer")
        await _mk_zone(sm, kind, "Bad")

        # 4. Ohne Schlafzimmer (kommt in der Seed-Liste nicht vor)
        ohne = await _mk_room(sm, f"{s}d")
        await _mk_zone(sm, ohne, "Bad")

        async with sm() as session:
            ergebnis = await referenzzonen_pro_zimmer(session, [normal, suite, kind, ohne])

        assert ergebnis[normal] == sz_normal
        assert ergebnis[suite] == sz_links, "L vertritt die Suite, nicht R"
        assert ergebnis[suite] != sz_rechts
        assert ergebnis[kind] == sz_kind, "Schlafzimmer, nicht Kinderzimmer"
        assert ergebnis[kind] != kz
        assert ohne not in ergebnis, "ohne Schlafzimmer -> kein Eintrag"
    finally:
        await _cleanup(sm)


async def test_leere_eingabe_macht_keine_abfrage(setup_engine: AsyncEngine) -> None:
    # Die Liste kann leer sein (Filter ohne Treffer). Dann darf der Helfer
    # kein ``IN ()`` bauen.
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with sm() as session:
        assert await referenzzonen_pro_zimmer(session, []) == {}


async def test_liste_liefert_ist_und_soll_der_referenzzone(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)

        # Zimmer mit Schlafzimmer (19.5 °C) und Bad (24.0 °C). Das Bad ist
        # waermer — faende die Liste es, waere der Wert zu hoch und die
        # Hervorhebung blieb aus.
        room = await _mk_room(sm, f"{s}a")
        sz = await _mk_zone(sm, room, "Schlafzimmer")
        bad = await _mk_zone(sm, room, "Bad")
        await _mk_device_mit_messwert(sm, sz, uuid.uuid4().hex[:8], Decimal("19.5"))
        await _mk_device_mit_messwert(sm, bad, uuid.uuid4().hex[:8], Decimal("24.0"))
        await _mk_hard_clamp(sm, room, Decimal("22.0"))

        resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})
        assert resp.status_code == 200, resp.text
        zeile = next(r for r in resp.json() if r["id"] == room)

        assert zeile["reference_zone_id"] == sz
        assert zeile["mean_temperature_c"] == 19.5, "Schlafzimmer, nicht Bad"
        assert zeile["engine_setpoint_c"] == 22.0
    finally:
        await _cleanup(sm)


async def test_decimal_kommt_als_json_zahl_nicht_als_string(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Struktureller Test am rohen Antwort-Text (§5.63).

    ``resp.json()`` wuerde ``"19.5"`` und ``19.5`` beide als Wert liefern,
    und der Vergleich mit ``== 19.5`` faellt nur bei einem der beiden auf.
    Deshalb hier die Form im Text: kein Anfuehrungszeichen hinter dem
    Doppelpunkt. Das Frontend rechnet mit der Zahl (``ist < soll - 2``) —
    ein String wuerde dort zu einer Zeichen-Vergleich-Falle.
    """
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)
        room = await _mk_room(sm, f"{s}a")
        sz = await _mk_zone(sm, room, "Schlafzimmer")
        await _mk_device_mit_messwert(sm, sz, uuid.uuid4().hex[:8], Decimal("18.5"))
        await _mk_hard_clamp(sm, room, Decimal("21.0"))

        resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})
        assert resp.status_code == 200, resp.text

        # Den Block dieses Zimmers aus dem Rohtext schneiden.
        rohe_zeile = next(
            teil
            for teil in re.findall(r"\{[^{}]*\}", resp.text)
            if f'"id":{room},' in teil.replace(" ", "")
        )
        assert '"mean_temperature_c":18.5' in rohe_zeile.replace(" ", ""), rohe_zeile
        assert '"engine_setpoint_c":21.0' in rohe_zeile.replace(" ", ""), rohe_zeile
        assert '"mean_temperature_c":"' not in rohe_zeile.replace(" ", "")
        assert '"engine_setpoint_c":"' not in rohe_zeile.replace(" ", "")

        # Und die Typen nach dem Parsen, damit der Test nicht nur die
        # Schreibweise prueft.
        zeile = next(r for r in json.loads(resp.text) if r["id"] == room)
        assert isinstance(zeile["mean_temperature_c"], float)
        assert isinstance(zeile["engine_setpoint_c"], float)
    finally:
        await _cleanup(sm)


async def test_ohne_messwert_und_ohne_zone_bleibt_null(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)

        # a) Schlafzimmer ohne Geraet -> Ist null, Soll steht
        kein_geraet = await _mk_room(sm, f"{s}a")
        sz_a = await _mk_zone(sm, kein_geraet, "Schlafzimmer")
        await _mk_hard_clamp(sm, kein_geraet, Decimal("20.0"))

        # b) Geraet ohne Messwert -> Ist null
        ohne_wert = await _mk_room(sm, f"{s}b")
        sz_b = await _mk_zone(sm, ohne_wert, "Schlafzimmer")
        await _mk_device_mit_messwert(sm, sz_b, uuid.uuid4().hex[:8], None)

        # c) kein Schlafzimmer -> keine Referenzzone, Ist null
        ohne_sz = await _mk_room(sm, f"{s}c")
        await _mk_zone(sm, ohne_sz, "Bad")

        # d) keine Engine-Zeile -> Soll null, kein Fehler
        ohne_engine = await _mk_room(sm, f"{s}d")
        sz_d = await _mk_zone(sm, ohne_engine, "Schlafzimmer")
        await _mk_device_mit_messwert(sm, sz_d, uuid.uuid4().hex[:8], Decimal("17.0"))

        resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})
        assert resp.status_code == 200, resp.text
        nach_id = {r["id"]: r for r in resp.json()}

        assert nach_id[kein_geraet]["reference_zone_id"] == sz_a
        assert nach_id[kein_geraet]["mean_temperature_c"] is None
        assert nach_id[kein_geraet]["engine_setpoint_c"] == 20.0

        assert nach_id[ohne_wert]["reference_zone_id"] == sz_b
        assert nach_id[ohne_wert]["mean_temperature_c"] is None

        assert nach_id[ohne_sz]["reference_zone_id"] is None
        assert nach_id[ohne_sz]["mean_temperature_c"] is None

        assert nach_id[ohne_engine]["mean_temperature_c"] == 17.0
        assert nach_id[ohne_engine]["engine_setpoint_c"] is None
    finally:
        await _cleanup(sm)


async def test_soll_aelter_als_eine_stunde_zaehlt_nicht(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Der Frische-Filter aus ``latest_hard_clamp_setpoint_per_room``.

    Ein Zimmer, dessen Engine seit zwei Stunden nichts geschrieben hat,
    zeigt **kein** Soll. Das ist die richtige Richtung: eine alte Zahl
    neben einem frischen Ist-Wert liest sich wie ein Vergleich und ist
    keiner (§5.79, dritter Teil).
    """
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)
        room = await _mk_room(sm, f"{s}a")
        sz = await _mk_zone(sm, room, "Schlafzimmer")
        await _mk_device_mit_messwert(sm, sz, uuid.uuid4().hex[:8], Decimal("18.0"))
        async with sm() as session:
            session.add(
                EventLog(
                    time=datetime.now(tz=UTC) - timedelta(hours=2),
                    room_id=room,
                    evaluation_id=uuid.uuid4(),
                    layer=EventLogLayer.HARD_CLAMP,
                    setpoint_in=Decimal("21.0"),
                    setpoint_out=Decimal("21.0"),
                    reason=CommandReason.OCCUPIED_SETPOINT,
                )
            )
            await session.commit()

        resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})
        zeile = next(r for r in resp.json() if r["id"] == room)
        assert zeile["mean_temperature_c"] == 18.0
        assert zeile["engine_setpoint_c"] is None
    finally:
        await _cleanup(sm)


# ---------------------------------------------------------------------------
# Der Soll ist der der Referenzzone (Befund des Betreibers, 31.10.2026)
# ---------------------------------------------------------------------------


async def test_soll_ist_der_der_referenzzone_nicht_der_des_zimmers(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """**Der Befund, als Test.** Zimmer-Soll 21, Schlafzimmer-Soll 23.

    Zimmer 107 am 30.10.2026: die Liste zeigte „Soll 21,0 °C", waehrend
    eine Uebersteuerung auf 23 °C fuer die Zone galt und das Geraet 23
    fuhr. Der Grund war nicht die Uebersteuerung, sondern die Spalte: das
    **Ist** war seit dem 15.10. das der Referenzzone, der **Soll** der des
    Zimmers. Zwei Spalten nebeneinander, die von verschiedenen Dingen
    sprachen.

    Eine Zonen-Uebersteuerung aendert den Zimmerwert nicht — sie steht in
    ``zone_overrides`` und wird erst im Dispatch je Zone eingesetzt. Genau
    deshalb genuegt es nicht, den Zimmerwert zu zeigen.
    """
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)

        room = await _mk_room(sm, f"{s}z")
        sz = await _mk_zone(sm, room, "Schlafzimmer")
        bad = await _mk_zone(sm, room, "Bad")
        await _mk_device_mit_messwert(sm, sz, uuid.uuid4().hex[:8], Decimal("22.5"))
        await _mk_hard_clamp(sm, room, Decimal("21.0"), zonen={sz: 23, bad: 21})

        resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})
        assert resp.status_code == 200, resp.text
        zeile = next(r for r in resp.json() if r["id"] == room)

        assert zeile["reference_zone_id"] == sz
        assert zeile["engine_setpoint_c"] == 23.0, (
            "der Soll der Referenzzone, nicht der 21,0 des Zimmers"
        )
    finally:
        await _cleanup(sm)


async def test_ohne_zonenwert_bleibt_der_zimmerwert(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Der Rueckfall, und er hat zwei echte Faelle.

    Eine HARD_CLAMP-Zeile ohne Zonen-Bericht gibt es in der ersten Minute
    nach einem Deploy — bis der erste Engine-Lauf je Zimmer durch ist —
    und bei jeder Zeile aus der Zeit vor dem 31.10.2026. Dann gilt der
    Zimmerwert, also die Anzeige von vorher.

    Ohne diese Pruefung waere der Rueckfall unbelegt, und ein Fehler darin
    zeigte sich als leere Spalte genau in der Minute, in der jemand nach
    einem Deploy hinsieht.
    """
    sm = async_sessionmaker(setup_engine, expire_on_commit=False)
    s = uuid.uuid4().hex[:8]
    try:
        await _login_admin(http_client, sm)

        room = await _mk_room(sm, f"{s}r")
        sz = await _mk_zone(sm, room, "Schlafzimmer")
        await _mk_device_mit_messwert(sm, sz, uuid.uuid4().hex[:8], Decimal("20.0"))
        await _mk_hard_clamp(sm, room, Decimal("19.0"))

        resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})
        zeile = next(r for r in resp.json() if r["id"] == room)

        assert zeile["engine_setpoint_c"] == 19.0
    finally:
        await _cleanup(sm)
