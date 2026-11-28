"""Entprellen der Sollwert-Befehle (Sprint 25 T1, gebaut 27.11.2026).

**Hier ist das Fenster an.** Die uebrige Suite laeuft mit
``SOLLWERT_ENTPRELL_S=0`` (Begruendung im Kopf von ``conftest.py``): die
dortigen Tests pruefen, **was** gesendet wird, nicht **wann**. Diese Datei
ist das Gegenstueck — sie prueft das Wann, und zwar durch **denselben
Dispatch**, den der Betrieb benutzt, inklusive zweier Ticks.

**Warum das zusammengehoert.** Ein Mechanismus, der suiteweit abgeschaltet
ist und nur in seinen eigenen Unit-Tests vorkommt, ist ein gruener Lauf,
der nichts geprueft hat (Paragraph 5.55). Der Abschnitt „durch den
Dispatch" unten ist der Teil, der das verhindert.

**Die Uhr ist ``time.time``, und sie wird nicht eingefroren.** Das Fenster
rechnet in Sekunden; die Tests setzen den Merker mit einer Zeit in der
Vergangenheit, statt die Uhr anzuhalten. Eine eingefrorene Uhr neben einem
``time.time()`` im Dienst waere die Falle aus Paragraph 5.59 in beide
Richtungen.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    OverrideSource,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import entprellen, redis_client
from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone

from .conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: Room.number = VARCHAR(20). ``t25-<4hex>`` = 8 Zeichen.
PREFIX = "t25"
DEV_EUI_PATTERN = "d25%"

#: Das Fenster, mit dem diese Datei rechnet. Klein, damit kein Test
#: wartet — die Tests setzen den Merker mit einer Zeit in der
#: Vergangenheit, statt Sekunden zu verstreichen.
FENSTER_S = 60


# ---------------------------------------------------------------------------
# Ein Redis-Doppelgaenger, der nur kann, was dieses Modul benutzt.
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Redis im Speicher — so viel, wie der Dispatch anfasst.

    ``store`` haelt die **Hashes** dieses Moduls (``entprellen``),
    ``flach`` die Zeichenketten der Nachbarn: ``resync_flag`` holt sein
    Flag mit ``getdel``, ``engine_abgleich`` zaehlt mit ``incr`` und
    sperrt mit ``set(nx=...)``. Beide laufen im selben Dispatch, und ein
    Doppelgaenger, der nur die eigenen Aufrufe kennt, bricht dort ab, wo
    der Nachbar beginnt.

    TTL wird ignoriert — sie ist eine Obergrenze gegen eingefrorene
    Merker, keine Zusicherung, auf der eine Entscheidung steht.

    ``kaputt`` macht jeden Aufruf zu einem ``redis.RedisError``. Damit
    laesst sich die Pflicht aus Paragraph 0 S5 pruefen: bei Stoerung wird
    **gesendet**.

    ``aufrufe`` zaehlt **nur** die Zugriffe auf die Hashes dieses Moduls.
    Sonst koennte der Test „abgeschaltet und doch an Redis gewesen" nicht
    unterscheiden, wer dort war.
    """

    def __init__(self, *, kaputt: bool = False) -> None:
        self.store: dict[str, dict[str, str]] = {}
        self.flach: dict[str, str] = {}
        self.kaputt = kaputt
        self.aufrufe = 0

    def _pruefe(self, *, eigen: bool = False) -> None:
        if eigen:
            self.aufrufe += 1
        if self.kaputt:
            raise redis.RedisError("Doppelgaenger: Redis nicht erreichbar")

    # --- Hashes: das Entprellen -----------------------------------------
    def hgetall(self, key: str) -> dict[str, str]:
        self._pruefe(eigen=True)
        return dict(self.store.get(key, {}))

    def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self._pruefe(eigen=True)
        self.store.setdefault(key, {}).update(mapping)
        return len(mapping)

    def delete(self, key: str) -> int:
        self._pruefe(eigen=True)
        weg = self.store.pop(key, None) is not None
        return 1 if weg or self.flach.pop(key, None) is not None else 0

    # --- Zeichenketten: die Nachbarn im selben Dispatch -----------------
    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        self._pruefe()
        if nx and key in self.flach:
            return None
        self.flach[key] = value
        return True

    def get(self, key: str) -> str | None:
        self._pruefe()
        return self.flach.get(key)

    def getdel(self, key: str) -> str | None:
        self._pruefe()
        return self.flach.pop(key, None)

    def incr(self, key: str) -> int:
        self._pruefe()
        neu = int(self.flach.get(key, "0")) + 1
        self.flach[key] = str(neu)
        return neu

    def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002 - TTL ignoriert
        self._pruefe()
        return key in self.store or key in self.flach


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    falsch = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: falsch)
    return falsch


@pytest.fixture
def entprellen_an(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schaltet das Fenster **an** — gegen die Vorgabe der Suite.

    ``conftest`` setzt es auf 0; hier ist es der Gegenstand.
    """
    monkeypatch.setenv("SOLLWERT_ENTPRELL_S", str(FENSTER_S))
    get_settings.cache_clear()
    assert get_settings().sollwert_entprell_s == FENSTER_S


# ---------------------------------------------------------------------------
# Der Dienst
# ---------------------------------------------------------------------------


def test_die_erste_aenderung_wird_gesammelt(fake_redis: _FakeRedis) -> None:
    urteil = entprellen.pruefe("d2500000000001", 25, fenster_s=FENSTER_S)
    assert urteil.senden is False
    assert urteil.alter_s == 0
    assert "gesammelt" in urteil.grund
    assert fake_redis.store, "kein Merker angelegt"


def test_eine_zweite_aenderung_verschiebt_das_fenster_nicht(fake_redis: _FakeRedis) -> None:
    """Sonst bekaeme ein Geraet mit wechselndem Wunsch **nie** einen Befehl.

    Dieselbe Falle wie bei der TTL in ``engine_abgleich.versuch_gezaehlt``:
    wer bei jeder Aenderung den Anfang neu setzt, baut ein Fenster, das
    nie ablaeuft.

    **Zwischen den beiden Aufrufen muss Zeit liegen** — sonst prueft der
    Test nichts. Die erste Fassung rief zweimal hintereinander auf, beide
    innerhalb derselben Sekunde: ``seit`` und ``jetzt`` waren dann
    dieselbe Zahl, und die Mutationsprobe „setze den Anfang neu" blieb
    **gruen** (Paragraph 5.55). Die halbe Minute unten ist der ganze
    Unterschied zwischen einem Beleg und einer Behauptung.
    """
    eui = "d2500000000002"
    entprellen.pruefe(eui, 25, fenster_s=FENSTER_S)

    # Dreissig Sekunden sind vergangen — gesetzt statt abgewartet.
    vor_dreissig = int(time.time()) - 30
    fake_redis.store[f"entprell:sollwert:{eui}"]["seit"] = str(vor_dreissig)

    urteil = entprellen.pruefe(eui, 22, fenster_s=FENSTER_S)
    assert urteil.senden is False
    assert urteil.alter_s == 30, "das Alter kommt nicht vom alten Anfang"
    eintrag = fake_redis.store[f"entprell:sollwert:{eui}"]
    assert eintrag["seit"] == str(vor_dreissig), "das Fenster ist verschoben worden"
    # Der Wert ist nachgezogen — er steht fuer das Protokoll da, nicht
    # fuer den Versand.
    assert eintrag["wert"] == "22"


def test_nach_ablauf_wird_gesendet_und_der_merker_geloescht(fake_redis: _FakeRedis) -> None:
    eui = "d2500000000003"
    entprellen.pruefe(eui, 25, fenster_s=FENSTER_S)
    # Den Merker in die Vergangenheit setzen, statt zu warten.
    fake_redis.store[f"entprell:sollwert:{eui}"]["seit"] = str(int(time.time()) - FENSTER_S - 1)

    urteil = entprellen.pruefe(eui, 25, fenster_s=FENSTER_S)
    assert urteil.senden is True
    assert "abgelaufen" in urteil.grund
    assert f"entprell:sollwert:{eui}" not in fake_redis.store, "Merker nicht geloescht"


def test_genau_auf_der_grenze_wird_gesendet(fake_redis: _FakeRedis) -> None:
    """``>=`` und nicht ``>``: eine Sekunde Streit ueber die Grenze ist
    keine Entscheidung, aber ein Fenster, das bei genau 60 noch sammelt,
    verschiebt den Versand um einen ganzen Tick.
    """
    eui = "d2500000000004"
    entprellen.pruefe(eui, 25, fenster_s=FENSTER_S)
    fake_redis.store[f"entprell:sollwert:{eui}"]["seit"] = str(int(time.time()) - FENSTER_S)
    assert entprellen.pruefe(eui, 25, fenster_s=FENSTER_S).senden is True


def test_fenster_null_sendet_und_fasst_redis_nicht_an(fake_redis: _FakeRedis) -> None:
    """Abgeschaltet heisst: keine Wartezeit **und** kein Zustand.

    Ein abgeschalteter Mechanismus, der trotzdem Schluessel anlegt, ist
    ein Rest, den beim naechsten Einschalten niemand erwartet.
    """
    urteil = entprellen.pruefe("d2500000000005", 25, fenster_s=0)
    assert urteil.senden is True
    assert urteil.grund == "entprellen_aus"
    assert fake_redis.aufrufe == 0


def test_bei_redis_ausfall_wird_gesendet(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Pflicht aus Paragraph 0 S5 — und die **andere** Richtung als beim Abgleich.

    Dort verhindert die Sperre eine Nachsendung, die Batterie kostet und
    nichts bewirkt: ohne Sperre lieber nicht senden. Hier verzoegert der
    Merker einen Befehl, den die Steuerung **will**: ohne Merker lieber
    senden. Ein Puffer, der bei Stoerung Befehle verschluckt, ist
    schlimmer als keiner.
    """
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _FakeRedis(kaputt=True))
    with caplog.at_level(logging.WARNING, logger="heizung.services.entprellen"):
        urteil = entprellen.pruefe("d2500000000006", 25, fenster_s=FENSTER_S)
    assert urteil.senden is True
    assert urteil.grund == "entprellen_ohne_redis"


def test_ein_unlesbarer_merker_gilt_als_keiner(fake_redis: _FakeRedis) -> None:
    """Ein kaputter Schluessel darf den Tick nicht abbrechen.

    Er wird wie „kein Merker" gelesen, der naechste Aufruf legt ihn neu.
    """
    eui = "d2500000000007"
    fake_redis.store[f"entprell:sollwert:{eui}"] = {"wert": "x", "seit": "keine-zahl"}
    urteil = entprellen.pruefe(eui, 25, fenster_s=FENSTER_S)
    assert urteil.senden is False
    assert fake_redis.store[f"entprell:sollwert:{eui}"]["seit"].isdigit()


def test_verwirf_loescht_und_wirft_nicht(fake_redis: _FakeRedis) -> None:
    eui = "d2500000000008"
    entprellen.pruefe(eui, 25, fenster_s=FENSTER_S)
    entprellen.verwirf(eui)
    assert f"entprell:sollwert:{eui}" not in fake_redis.store
    # Zweimal loeschen ist kein Fehler — im Tick kommt es vor.
    entprellen.verwirf(eui)


def test_verwirf_bei_redis_ausfall_wirft_nicht(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der Tick darf an einem Redis-Ausfall nicht sterben (Paragraph 0 S5)."""
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _FakeRedis(kaputt=True))
    entprellen.verwirf("d2500000000009")


# ---------------------------------------------------------------------------
# Durch den Dispatch — dieselbe Stelle, die im Betrieb sendet.
# ---------------------------------------------------------------------------

# ``asyncio_mode = "auto"`` (pyproject): ``async def test_`` genuegt, und
# ein ``pytestmark = pytest.mark.asyncio`` haette die synchronen Tests
# oben mitmarkiert — pytest warnt dann je Test.


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
    await engine.dispose()


SendeMock = Callable[[str, int], Awaitable[str]]


@pytest.fixture
def gesendet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Sammelt, was hinausgegangen waere. Vorbild: ``test_engine_multivicki_write``."""
    liste: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        liste.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return liste


async def _zimmer_mit_geraet(session: AsyncSession) -> tuple[Room, HeatingZone, Device]:
    short = uuid.uuid4().hex[:4]
    rt = RoomType(name=f"{PREFIX}-rt-{short}", default_t_occupied=Decimal("22.0"))
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    dev = Device(
        dev_eui=f"d25{uuid.uuid4().hex[:13]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"{PREFIX}-v-{short}",
        heating_zone_id=zone.id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    return room, zone, dev


async def _ticks(session: AsyncSession, room: Room) -> tuple[list[dict], list[dict]]:
    return await _dispatch_downlinks_per_zone(
        session=session,
        room_id=room.id,
        target_setpoint_c=25,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )


async def test_der_erste_tick_sendet_nicht_und_schreibt_keinen_befehl(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
    entprellen_an: None,
) -> None:
    """Gesammelt statt gesendet — und **kein** ``ControlCommand``.

    Ein Befehl ohne Downlink waere eine Zeile, die aussieht wie ein
    Versuch. Dieselbe Haltung wie bei der Hysterese: wer nicht sendet,
    schreibt nichts.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)

    per_dev, per_zone = await _ticks(db_session, room)

    assert gesendet == []
    assert len(per_dev) == 1
    assert per_dev[0]["status"] == "entprellt"
    assert per_dev[0]["gesendet_c"] is None
    assert "entprellt_gesammelt" in per_dev[0]["hysteresis_reason"]
    assert per_zone[0]["count_skipped"] == 1
    assert per_zone[0]["count_sent"] == 0

    befehle = (
        await db_session.execute(select(ControlCommand).where(ControlCommand.device_id == dev.id))
    ).all()
    assert befehle == [], "ein Befehl ohne Downlink waere eine Zeile, die luegt"


async def test_der_zweite_tick_nach_ablauf_sendet(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
    entprellen_an: None,
) -> None:
    """Der Gewinn: **ein** Publish statt zwei.

    Zwischen den Ticks wird der Merker in die Vergangenheit gesetzt —
    das ist die Minute, die im Betrieb vergeht.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)
    await _ticks(db_session, room)
    assert gesendet == []

    fake_redis.store[f"entprell:sollwert:{dev.dev_eui}"]["seit"] = str(
        int(time.time()) - FENSTER_S - 1
    )
    per_dev, per_zone = await _ticks(db_session, room)

    assert gesendet == [(dev.dev_eui, 25)]
    assert per_dev[0]["status"] == "sent"
    assert per_dev[0]["gesendet_c"] == 25
    assert "entprellt_abgelaufen" in per_dev[0]["hysteresis_reason"]
    assert per_zone[0]["count_sent"] == 1


async def test_ein_boost_geht_sofort_hinaus_und_loescht_den_merker(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
    entprellen_an: None,
) -> None:
    """Die eine Sollwertaenderung, die der Gast sofort spueren soll.

    **Und der Merker muss weg.** Bliebe er stehen, folgte dem Boost eine
    Minute spaeter der gesammelte alte Wert — und naehme ihn zurueck. Das
    ist der Teil, den der Brief vom 05.11.2026 ausdruecklich nennt.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)
    # Erster Tick sammelt.
    await _ticks(db_session, room)
    assert f"entprell:sollwert:{dev.dev_eui}" in fake_redis.store

    per_dev, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=25,
        base_reason=CommandReason.MANUAL,
        eval_id=uuid.uuid4(),
        uebersteuerung_quelle=OverrideSource.FRONTEND_BOOST.value,
    )

    assert gesendet == [(dev.dev_eui, 25)]
    assert per_dev[0]["status"] == "sent"
    assert "Boost umgeht das Entprellen" in per_dev[0]["hysteresis_reason"]
    assert f"entprell:sollwert:{dev.dev_eui}" not in fake_redis.store


async def test_eine_andere_uebersteuerung_wird_entprellt(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
    entprellen_an: None,
) -> None:
    """Nur der **Boost** umgeht das Fenster, nicht jede Uebersteuerung.

    Ohne diesen Test waere „Boost" ein Name ohne Wirkung: ein Vergleich,
    der auf jede Quelle passt, ist keiner.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)

    per_dev, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=25,
        base_reason=CommandReason.MANUAL,
        eval_id=uuid.uuid4(),
        uebersteuerung_quelle=OverrideSource.FRONTEND_24H.value,
    )

    assert gesendet == []
    assert per_dev[0]["status"] == "entprellt"


async def test_wenn_nichts_zu_senden_ist_faellt_der_merker(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
    entprellen_an: None,
) -> None:
    """Der eigentliche Gewinn: 20, dann 25, dann wieder 20 — **kein** Downlink.

    Tick 1 will 25 und sammelt. Tick 2 will wieder den Wert, den das
    Geraet schon gesendet bekam — die Hysterese schweigt, und der Merker
    muss fallen. Bliebe er stehen, waere das Fenster beim naechsten echten
    Wunsch schon abgelaufen und der ginge sofort hinaus.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)
    # Ein bereits gesendeter Befehl auf 20: die Hysterese schweigt dann
    # fuer einen Tick, der 20 will.
    jetzt = datetime.now(tz=UTC)
    db_session.add(
        ControlCommand(
            device_id=dev.id,
            target_setpoint=Decimal(20),
            reason=CommandReason.OCCUPIED_SETPOINT,
            issued_at=jetzt - timedelta(minutes=5),
            sent_to_gateway_at=jetzt - timedelta(minutes=5),
        )
    )
    await db_session.flush()

    # Tick 1: die Steuerung will 25 -> gesammelt.
    await _ticks(db_session, room)
    assert f"entprell:sollwert:{dev.dev_eui}" in fake_redis.store
    assert gesendet == []

    # Tick 2: sie will wieder 20 -> Hysterese schweigt, Merker faellt.
    per_dev, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room.id,
        target_setpoint_c=20,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
    )
    assert gesendet == []
    assert per_dev[0]["status"] == "skipped_hysteresis"
    assert f"entprell:sollwert:{dev.dev_eui}" not in fake_redis.store, (
        "der Merker haengt — der naechste echte Wunsch ginge sofort hinaus"
    )


async def test_ohne_entprellen_sendet_der_erste_tick(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
) -> None:
    """Die Gegenprobe, und sie ist die Vorgabe der uebrigen Suite.

    Ohne diesen Test waere nicht belegt, dass ``SOLLWERT_ENTPRELL_S=0``
    wirklich abschaltet — und die 2300 anderen Tests liefen auf einer
    Annahme.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)
    assert get_settings().sollwert_entprell_s == 0

    per_dev, _ = await _ticks(db_session, room)

    assert gesendet == [(dev.dev_eui, 25)]
    assert per_dev[0]["status"] == "sent"
    assert fake_redis.aufrufe == 0, "abgeschaltet und doch an Redis gewesen"


async def test_eine_belegung_aendert_am_entprellen_nichts(
    db_session: AsyncSession,
    gesendet: list[tuple[str, int]],
    fake_redis: _FakeRedis,
    entprellen_an: None,
) -> None:
    """Das Fenster haengt am **Geraet**, nicht am Zustand des Zimmers.

    Die Zeile steht hier, weil der naheliegende Einwand lautet: „bei
    einem belegten Zimmer sollte sofort gesendet werden." Das ist eine
    Entscheidung, die niemand getroffen hat — und sie waere falsch, denn
    die ueberfluessige Bewegung entsteht genau dort, wo die Steuerung
    waehrend einer Belegung ihre Meinung aendert.
    """
    room, zone, dev = await _zimmer_mit_geraet(db_session)
    jetzt = datetime.now(tz=UTC)
    db_session.add(
        Occupancy(
            room_id=room.id,
            check_in=jetzt - timedelta(hours=1),
            check_out=jetzt + timedelta(days=1),
            is_active=True,
        )
    )
    db_session.add(
        ManualOverride(
            room_id=room.id,
            setpoint=Decimal("25.0"),
            source=OverrideSource.FRONTEND_24H,
            expires_at=jetzt + timedelta(hours=4),
        )
    )
    await db_session.flush()

    per_dev, _ = await _ticks(db_session, room)
    assert gesendet == []
    assert per_dev[0]["status"] == "entprellt"
