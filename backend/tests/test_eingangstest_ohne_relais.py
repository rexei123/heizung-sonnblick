"""Der Eingangstest prüft keine Relais — und die Pool-Liste zeigt sie trotzdem.

**Latenter Fehler, als solcher gefunden.** `_cmd_inbound_test` läuft über
`get_pool_devices()`, und dieser Helfer filtert nach Zone und Lebenszyklus,
nicht nach Geräteart. Der Eingangstest setzt Sollwerte (`0x51`) und
beurteilt das Gerät daran, ob es sie meldet und ob sich das Ventil bewegt.
Ein Relais hat **kein Sollwert-Register und kein Ventil**: der Befehl geht
ins Leere, die Bestätigung bleibt aus, und das Gerät fällt durch eine
Prüfung, die es nicht betrifft.

Heute liegt kein Relais im Pool — die beiden im Haus sind zugeordnet und
in Betrieb. Beim nächsten Reserve-Relais wäre es einer, und zwar derselbe,
den #410 im Engine-Pfad beseitigt hat: sinnlose `0x51` an Geräte ohne
Sollwert.

**Gefiltert wird im Lauf, nicht in `get_pool_devices`.** Die Pool-Liste
soll das Relais zeigen — wer ein Reserve-Relais einlagert, will es dort
sehen. Ein Filter in der Leseschicht würde es unsichtbar machen und damit
ein zweites Problem schaffen, um das erste zu lösen. Beides prüft diese
Datei.
"""

from __future__ import annotations

import argparse
import os
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.scripts import pair_devices
from heizung.services.device_service import get_pool_devices

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
PREFIX = "t-eing"

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


class Pool:
    def __init__(self, thermostat_id: int, relais_id: int, relais_label: str) -> None:
        self.thermostat_id = thermostat_id
        self.relais_id = relais_id
        self.relais_label = relais_label


@pytest_asyncio.fixture
async def session(setup_engine: Any) -> AsyncIterator[Any]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as s:
        try:
            yield s
        finally:
            await s.rollback()


@pytest_asyncio.fixture
def patched_session_local(session: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``pair_devices.SessionLocal`` gibt die Test-Session heraus.

    Das Muster aus ``test_pair_devices_cli``: der Befehl oeffnet sonst
    seine **eigene** Session auf demselben Pool, und zwei gleichzeitige
    Operationen auf einer Verbindung enden in
    „another operation is in progress" — derselbe Nachbarschaftsschaden
    wie in Paragraph 5.14, nur ueber den Pool statt ueber den Loop.
    """

    @asynccontextmanager
    async def fake_factory() -> AsyncIterator[Any]:
        yield session

    monkeypatch.setattr(pair_devices, "SessionLocal", fake_factory)
    return session


@pytest_asyncio.fixture
async def pool(session: Any, patched_session_local: Any) -> Pool:
    """Zwei Geraete im Pool: ein Vicki und ein Relais, beide ohne Zone.

    Nur ``flush``, kein ``commit``: die Session wird am Ende
    zurueckgerollt, und damit bleibt nichts liegen (Paragraph 5.39).
    """
    jetzt = datetime.now(tz=UTC)
    thermostat = Device(
        dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"{PREFIX}-t",
        health_state="healthy",
        created_at=jetzt - timedelta(minutes=5),
    )
    relais = Device(
        dev_eui=f"deadbeef{uuid.uuid4().hex[:8]}",
        kind=DeviceKind.RELAY,
        vendor=DeviceVendor.MCLIMATE,
        model="16ASPM",
        label=f"{PREFIX}-r",
        health_state="healthy",
        created_at=jetzt - timedelta(minutes=4),
    )
    session.add_all([thermostat, relais])
    await session.flush()
    return Pool(thermostat.id, relais.id, relais.label or "")


class Mitschreiber:
    """Statt des echten Laufs: wer wäre geprüft worden?"""

    def __init__(self) -> None:
        self.geraete: list[list[str]] = []

    async def __call__(self, session: Any, devices: Sequence[Device], **kwargs: Any) -> Any:
        self.geraete.append([d.label or d.dev_eui for d in devices])
        return _LeererReport()


class _LeererReport:
    """Das Wenige, was ``_cmd_inbound_test`` nach dem Lauf anfasst."""

    results: list[Any] = []
    exit_code = 0


@pytest.fixture
def lauf(monkeypatch: pytest.MonkeyPatch) -> Mitschreiber:
    m = Mitschreiber()
    monkeypatch.setattr(pair_devices, "run_batch_inbound_test", m)
    monkeypatch.setattr(pair_devices, "format_report", lambda report: "")
    return m


def _args(**extra: Any) -> argparse.Namespace:
    grund = {
        "devices": None,
        "user_email": None,
        "timeout": 1,
        "poll_interval": 1,
        "require_motor": False,
        "no_valve_check": True,
        "heartbeat_wait": 0,
        "no_reset": True,
        "resume": False,
        "sperre_ttl": 0,
    }
    grund.update(extra)
    return argparse.Namespace(**grund)


async def test_das_relais_wird_uebersprungen(pool: Pool, lauf: Mitschreiber) -> None:
    """**Der Fehler, der sonst beim naechsten Reserve-Relais aufgetreten waere.**

    Der Lauf bekommt den Vicki und **nicht** das Relais. Geprueft wird die
    Liste, die der Lauf erhaelt — nicht eine Ausgabe, denn eine Zeile im
    Protokoll beweist nicht, dass kein Befehl hinausging.
    """
    code = await pair_devices._cmd_inbound_test(_args())
    assert code == 0
    assert len(lauf.geraete) == 1
    # **Nur die eigenen Geraete pruefen** (Paragraph 5.39): in der Test-DB
    # liegen Reste anderer Dateien im Pool, und ein Vergleich auf die
    # ganze Liste waere von ihnen abhaengig.
    gesehen = lauf.geraete[0]
    assert f"{PREFIX}-t" in gesehen, "der Vicki gehoert geprueft"
    assert pool.relais_label not in gesehen, f"das Relais nicht: {pool.relais_label}"


async def test_ein_pool_mit_nur_relais_laeuft_nicht_los(pool: Pool, lauf: Mitschreiber) -> None:
    """Bleibt nach dem Filter nichts uebrig, wird **gar nicht** gestartet.

    Ohne diese Bedingung liefe ``run_batch_inbound_test`` mit einer leeren
    Liste — ein Lauf, der nichts prueft und bestanden meldet (Paragraph
    5.55).
    """
    # Die Auswahl ``--devices`` nennt **nur** das Relais. Nach dem Filter
    # bleibt damit nichts, und das ist derselbe Zustand wie ein Pool, in
    # dem ausschliesslich Relais liegen -- ohne dafuer Geraete loeschen zu
    # muessen, die andere Tests noch brauchen.
    code = await pair_devices._cmd_inbound_test(_args(devices=pool.relais_label))
    assert code == 0
    assert lauf.geraete == [], "kein Lauf, wenn nach dem Filter nichts bleibt"


async def test_der_einzeltest_bricht_am_relais_ab(pool: Pool, lauf: Mitschreiber) -> None:
    """Beim Einzeltest ist das Geraet genannt — also Abbruch, nicht Ueberspringen.

    Ein Lauf, der das genannte Geraet still uebergeht und 0 zurueckgibt,
    sieht wie ein bestandener Test aus. Der Rueckgabewert ist hier die
    Aussage, nicht die Meldung.
    """
    code = await pair_devices._cmd_test(
        argparse.Namespace(
            device=str(pool.relais_id),
            user_email=None,
            timeout=1,
            poll_interval=1,
            require_motor=False,
            no_valve_check=True,
            heartbeat_wait=0,
            no_reset=True,
            resume=False,
            sperre_ttl=0,
        )
    )
    assert code == 1
    assert lauf.geraete == [], "kein Befehl an ein Relais"


async def test_der_einzeltest_laeuft_fuer_einen_vicki_weiter(
    pool: Pool, lauf: Mitschreiber
) -> None:
    """Die Gegenprobe: ohne sie waere „bricht immer ab" genauso gruen."""
    code = await pair_devices._cmd_test(
        argparse.Namespace(
            device=str(pool.thermostat_id),
            user_email=None,
            timeout=1,
            poll_interval=1,
            require_motor=False,
            no_valve_check=True,
            heartbeat_wait=0,
            no_reset=True,
            resume=False,
            sperre_ttl=0,
        )
    )
    assert code == 0
    assert lauf.geraete == [[f"{PREFIX}-t"]], "der Einzeltest prueft genau eines"


async def test_die_pool_liste_zeigt_das_relais_weiter(pool: Pool, session: Any) -> None:
    """**Der Filter gehoert in den Lauf, nicht in die Leseschicht.**

    Wer ein Reserve-Relais einlagert, will es in der Pool-Liste sehen. Ein
    Filter in ``get_pool_devices`` haette es unsichtbar gemacht — ein
    zweites Problem, um das erste zu loesen.
    """
    geraete = await get_pool_devices(session)
    ids = {g.id for g in geraete}
    assert pool.relais_id in ids, "das Relais bleibt im Pool sichtbar"
    assert pool.thermostat_id in ids
