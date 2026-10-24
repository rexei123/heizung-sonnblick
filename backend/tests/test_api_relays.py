"""Relais-Endpunkte und die Admin-Pruefung (Sprint 24b, Paket 6).

**Szenario 7 des Briefs und Mutationsprobe M12.** Jeder der fuenf
Handgriffe ist nur fuer Admins, und die Pruefung sitzt im **Backend**.
Eine Pruefung, die nur im Formular steht, gilt fuer die API nicht, fuer
ein Skript nicht und fuer einen spaeteren Massen-Handgriff nicht.

Die Tests fahren ueber den echten ASGI-Stack (``httpx.ASGITransport``),
also durch die Abhaengigkeiten hindurch — nicht gegen die
Endpunkt-Funktion. Nur so ist ``require_admin`` ueberhaupt im Spiel.

**Downlinks sind umgeleitet.** Die Bytes pruefen der Codec-Test und die
Adapter-Tests; hier geht es um Rollen, Reihenfolge und Audit.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path as FsPath
from typing import Any

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.api.v1 import relays as relays_api
from heizung.auth.dependencies import get_current_user
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind, UserRole
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.user import User

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"
PREFIX = "t24api"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason=SKIP_REASON)


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


@pytest_asyncio.fixture
async def mitgeschnitten(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Alle Downlinks der Endpunkte, ohne MQTT."""
    protokoll: dict[str, list[Any]] = {"relay": [], "child_lock": []}

    async def _rel(dev_eui: str, *args: Any, **kwargs: Any) -> str:
        protokoll["relay"].append((dev_eui, args, kwargs))
        return "topic"

    async def _cl(dev_eui: str, *args: Any, **kwargs: Any) -> str:
        protokoll["child_lock"].append((dev_eui, args, kwargs))
        return "topic"

    for name in (
        "setze_zustand_nach_stromrueckkehr",
        "setze_zustand_nach_ueberhitzung",
        "frage_zustand_nach_stromrueckkehr",
        "frage_zustand_nach_ueberhitzung",
    ):
        monkeypatch.setattr(relays_api.relay_adapter, name, _rel)
    for name in ("set_child_lock", "get_child_lock"):
        monkeypatch.setattr(relays_api.downlink_adapter, name, _cl)
    return protokoll


class Aufbau:
    def __init__(self, relais_id: int, thermostat_id: int, room_id: int) -> None:
        self.relais_id = relais_id
        self.thermostat_id = thermostat_id
        self.room_id = room_id


@pytest_asyncio.fixture
async def aufbau(setup_engine: AsyncEngine) -> AsyncIterator[Aufbau]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    short = uuid.uuid4().hex[:4]
    async with maker() as session:
        rt = RoomType(name=f"{PREFIX}-rt-{short}", is_bookable=False)
        session.add(rt)
        await session.flush()
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Barbereich")
        session.add(zone)
        await session.flush()
        relais = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            heating_zone_id=zone.id,
            health_state="healthy",
        )
        thermostat = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            heating_zone_id=zone.id,
            health_state="healthy",
        )
        session.add_all([relais, thermostat])
        await session.commit()
        ids = Aufbau(relais.id, thermostat.id, room.id)

    try:
        yield ids
    finally:
        async with maker() as session:
            await session.execute(
                text(
                    "DELETE FROM business_audit WHERE target_id = ANY(:d) AND target_type='device'"
                ),
                {"d": [ids.relais_id, ids.thermostat_id]},
            )
            await session.execute(
                text("DELETE FROM device WHERE id = ANY(:d)"),
                {"d": [ids.relais_id, ids.thermostat_id]},
            )
            await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
            await session.execute(
                text("DELETE FROM room_type WHERE name LIKE :p"), {"p": f"{PREFIX}-%"}
            )
            await session.commit()


def _nutzer(rolle: UserRole) -> User:
    """Ein Nutzer-Objekt ohne Datenbank — die Abhaengigkeit wird ersetzt."""
    return User(
        id=1,
        email=f"{rolle.value}@example.invalid",
        password_hash="x",
        role=rolle,
        is_active=True,
    )


@pytest_asyncio.fixture
async def client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """Client **ohne** Rollen-Ersatz: ``require_admin`` greift echt.

    Die Session-Abhaengigkeit wird auf die Test-Datenbank gelegt, die
    Rollen-Abhaengigkeiten **nicht** — genau das ist der Gegenstand der
    Pruefung.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[Any]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


# **Die Rolle wird ueber ``get_current_user`` injiziert, nicht ueber
# ``require_admin``.** Das ist der Kern dieser Datei, und der erste
# Versuch war falsch.
#
# Ersetzt man ``require_admin`` selbst, prueft man die Zeile nicht mehr,
# die M12 angreift — man ersetzt sie. Und laesst man einfach das Cookie
# weg, kommt man auch nicht ans Ziel: unter ``AUTH_ENABLED=false``
# liefert ``get_current_user`` einen **System-User** zurueck
# (``auth/dependencies.py:88``), und der traegt Admin-Rechte. Die erste
# Fassung dieser Tests bekam deshalb 422 statt 403 — die Endpunkt-Rumpfe
# liefen durch, und die Probe war wertlos.
#
# Mit einem injizierten Mitarbeiter laeuft ``require_admin`` echt und
# muss 403 werfen.
@pytest_asyncio.fixture
async def admin_client(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    app.dependency_overrides[get_current_user] = lambda: _nutzer(UserRole.ADMIN)
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def mitarbeiter_client(client: httpx.AsyncClient) -> AsyncIterator[httpx.AsyncClient]:
    """Ein angemeldeter **Mitarbeiter**, kein Admin — Szenario 7."""
    app.dependency_overrides[get_current_user] = lambda: _nutzer(UserRole.MITARBEITER)
    yield client
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Szenario 7 / M12 — ohne Admin geht nichts
# ---------------------------------------------------------------------------


WEGE = [
    ("post", "/api/v1/devices/{id}/relay/provision", None),
    ("post", "/api/v1/devices/{id}/relay/commission", None),
    ("delete", "/api/v1/devices/{id}/relay/commission", None),
    ("post", "/api/v1/devices/{id}/relay/release-protection", None),
]


@pytest.mark.parametrize(("methode", "pfad", "rumpf"), WEGE)
async def test_ohne_anmeldung_abgewiesen(
    mitarbeiter_client: httpx.AsyncClient,
    aufbau: Aufbau,
    methode: str,
    pfad: str,
    rumpf: dict[str, Any] | None,
) -> None:
    """**Szenario 7, Mutationsprobe M12.**

    Keine Sitzung, kein Recht. Erwartet wird 401 oder 403 — welcher von
    beiden, entscheidet die Auth-Schicht, und beides ist eine Abweisung.
    Ein 200 waere der Befund.
    """
    url = pfad.format(id=aufbau.relais_id)
    # ``AsyncClient.delete`` nimmt kein ``json`` — deshalb je Methode.
    if rumpf is None:
        antwort = await getattr(mitarbeiter_client, methode)(url)
    else:
        antwort = await getattr(mitarbeiter_client, methode)(url, json=rumpf)
    assert antwort.status_code in (401, 403), (
        f"{methode.upper()} {pfad} muss abweisen, war {antwort.status_code}: {antwort.text}"
    )


async def test_rollenwechsel_ohne_admin_abgewiesen(
    mitarbeiter_client: httpx.AsyncClient, aufbau: Aufbau
) -> None:
    antwort = await mitarbeiter_client.patch(
        f"/api/v1/devices/{aufbau.thermostat_id}/measure-only",
        json={"measure_only": True},
    )
    assert antwort.status_code in (401, 403)


async def test_rollenwechsel_ohne_admin_aendert_nichts(
    mitarbeiter_client: httpx.AsyncClient,
    aufbau: Aufbau,
    setup_engine: AsyncEngine,
    mitgeschnitten: dict[str, list[Any]],
) -> None:
    """Die Abweisung muss auch **wirken**, nicht nur antworten.

    Ein 403 mit geschriebener Aenderung waere die schlechteste aller
    Varianten: sie sieht nach Schutz aus und ist keiner.
    """
    await mitarbeiter_client.patch(
        f"/api/v1/devices/{aufbau.thermostat_id}/measure-only",
        json={"measure_only": True},
    )
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.thermostat_id)
        assert geraet is not None
        assert geraet.measure_only is False


# ---------------------------------------------------------------------------
# S4 — Inbetriebnahme nur mit beiden Ruecklesungen
# ---------------------------------------------------------------------------


async def test_inbetriebnahme_ohne_ruecklesungen_abgewiesen(
    admin_client: httpx.AsyncClient, aufbau: Aufbau
) -> None:
    """Auch ein Admin kann es nicht erzwingen (S4)."""
    antwort = await admin_client.post(f"/api/v1/devices/{aufbau.relais_id}/relay/commission")
    assert antwort.status_code == 422
    assert "Stromrueckkehr" in antwort.text
    assert "Ueberhitzungs-Erholung" in antwort.text


async def test_inbetriebnahme_mit_nur_einer_ruecklesung_abgewiesen(
    admin_client: httpx.AsyncClient, aufbau: Aufbau, setup_engine: AsyncEngine
) -> None:
    """**Mutationsprobe M9 ueber die API.**"""
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.relais_id)
        assert geraet is not None
        geraet.power_return_verified_at = datetime.now(tz=UTC)
        await session.commit()

    antwort = await admin_client.post(f"/api/v1/devices/{aufbau.relais_id}/relay/commission")
    assert antwort.status_code == 422
    assert "Ueberhitzungs-Erholung" in antwort.text


async def test_inbetriebnahme_mit_beiden_ruecklesungen_gelingt(
    admin_client: httpx.AsyncClient, aufbau: Aufbau, setup_engine: AsyncEngine
) -> None:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    jetzt = datetime.now(tz=UTC)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.relais_id)
        assert geraet is not None
        geraet.power_return_verified_at = jetzt - timedelta(minutes=5)
        geraet.overheating_recovery_verified_at = jetzt - timedelta(minutes=4)
        await session.commit()

    antwort = await admin_client.post(f"/api/v1/devices/{aufbau.relais_id}/relay/commission")
    assert antwort.status_code == 200, antwort.text
    rumpf = antwort.json()
    assert rumpf["commissioned_at"] is not None
    assert rumpf["power_return_verified"] is True
    assert rumpf["overheating_recovery_verified"] is True

    # Audit geschrieben.
    async with maker() as session:
        aktionen = (
            (
                await session.execute(
                    select(BusinessAudit.action).where(BusinessAudit.target_id == aufbau.relais_id)
                )
            )
            .scalars()
            .all()
        )
    assert "RELAY_COMMISSIONED" in aktionen


# ---------------------------------------------------------------------------
# Provisionierung
# ---------------------------------------------------------------------------


async def test_provisionierung_sendet_vier_downlinks_in_reihenfolge(
    admin_client: httpx.AsyncClient,
    aufbau: Aufbau,
    mitgeschnitten: dict[str, list[Any]],
) -> None:
    """Setzen, setzen, lesen, lesen — und das Ergebnis sagt „angefragt".

    Die Reihenfolge ist nicht beliebig: erst beide Werte setzen, dann
    beide abfragen, damit die Antworten einen zusammengehoerenden Stand
    beschreiben.
    """
    antwort = await admin_client.post(f"/api/v1/devices/{aufbau.relais_id}/relay/provision")
    assert antwort.status_code == 200, antwort.text
    rumpf = antwort.json()
    assert len(rumpf["gesendet"]) == 4
    assert rumpf["gesendet"][0].startswith("0x5E 02")
    assert rumpf["gesendet"][1].startswith("0x59 01")
    assert rumpf["gesendet"][2].startswith("0x5F")
    assert rumpf["gesendet"][3].startswith("0x5A")
    assert "naechsten Uplink" in rumpf["hinweis"], (
        "der Endpunkt darf kein Urteil behaupten — die Antworten kommen asynchron"
    )
    assert len(mitgeschnitten["relay"]) == 4


async def test_provisionierung_eines_thermostats_abgewiesen(
    admin_client: httpx.AsyncClient, aufbau: Aufbau
) -> None:
    antwort = await admin_client.post(f"/api/v1/devices/{aufbau.thermostat_id}/relay/provision")
    assert antwort.status_code == 422
    assert "kein Relais" in antwort.text


# ---------------------------------------------------------------------------
# Schutz-Sperre
# ---------------------------------------------------------------------------


async def test_freigabe_ohne_stehende_sperre_abgewiesen(
    admin_client: httpx.AsyncClient, aufbau: Aufbau
) -> None:
    antwort = await admin_client.post(
        f"/api/v1/devices/{aufbau.relais_id}/relay/release-protection"
    )
    assert antwort.status_code == 422


async def test_freigabe_hebt_die_sperre_auf_und_schreibt_audit(
    admin_client: httpx.AsyncClient, aufbau: Aufbau, setup_engine: AsyncEngine
) -> None:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.relais_id)
        assert geraet is not None
        geraet.protection_tripped_at = datetime.now(tz=UTC)
        geraet.protection_kind = "overheating"
        await session.commit()

    antwort = await admin_client.post(
        f"/api/v1/devices/{aufbau.relais_id}/relay/release-protection"
    )
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["gesperrt"] is False

    async with maker() as session:
        geraet = await session.get(Device, aufbau.relais_id)
        assert geraet is not None
        assert geraet.protection_tripped_at is None
        aktionen = (
            (
                await session.execute(
                    select(BusinessAudit.action).where(BusinessAudit.target_id == aufbau.relais_id)
                )
            )
            .scalars()
            .all()
        )
    assert "RELAY_PROTECTION_RELEASED" in aktionen


# ---------------------------------------------------------------------------
# Rolle „nur messen"
# ---------------------------------------------------------------------------


async def test_rolle_setzen_sendet_die_kindersicherung(
    admin_client: httpx.AsyncClient,
    aufbau: Aufbau,
    mitgeschnitten: dict[str, list[Any]],
    setup_engine: AsyncEngine,
) -> None:
    """Die Sperre gehoert zum Setzen der Rolle, nicht daneben (S7)."""
    antwort = await admin_client.patch(
        f"/api/v1/devices/{aufbau.thermostat_id}/measure-only",
        json={"measure_only": True},
    )
    assert antwort.status_code == 200, antwort.text
    rumpf = antwort.json()
    assert rumpf["measure_only"] is True
    assert rumpf["kindersicherung_gesendet"] is True
    assert len(mitgeschnitten["child_lock"]) == 2, "setzen und zuruecklesen"

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        geraet = await session.get(Device, aufbau.thermostat_id)
        assert geraet is not None
        assert geraet.measure_only is True


async def test_rolle_unveraendert_sendet_nichts(
    admin_client: httpx.AsyncClient,
    aufbau: Aufbau,
    mitgeschnitten: dict[str, list[Any]],
) -> None:
    """Idempotenz: kein Downlink, wenn sich nichts aendert (§0 S4)."""
    antwort = await admin_client.patch(
        f"/api/v1/devices/{aufbau.thermostat_id}/measure-only",
        json={"measure_only": False},
    )
    assert antwort.status_code == 200
    assert antwort.json()["kindersicherung_gesendet"] is False
    assert mitgeschnitten["child_lock"] == []


async def test_rolle_an_einem_relais_abgewiesen(
    admin_client: httpx.AsyncClient, aufbau: Aufbau
) -> None:
    """Ein Relais misst nicht."""
    antwort = await admin_client.patch(
        f"/api/v1/devices/{aufbau.relais_id}/measure-only",
        json={"measure_only": True},
    )
    assert antwort.status_code == 422
    assert "misst nicht" in antwort.text
