"""Die erschoepfte Abgleich-Lage bleibt stehen, bis das Geraet bestaetigt (Sprint 25, T3).

**Der Befund des Betreibers — Geraet 7, 01.11. bis 04.11.2026.** Der
Abgleich hatte nach drei erfolglosen Nachsendungen aufgegeben. Dann
verschob die Engine ihren Wunsch — Nachtabsenkung, Belegungswechsel — und
traf damit zufaellig den Wert, den das Geraet ohnehin hielt. Die
Aufraeum-Bedingung lautete bis zum 08.11.2026 ``ist_wert ==
zone_target_setpoint_c``, also "Geraet stimmt mit dem **aktuellen
Wunsch** ueberein". Sie griff, der Zaehler fiel, und der Befund war weg —
**ohne dass das Geraet je einen Befehl angenommen hatte.**

Beim naechsten Wunschwechsel begann das Spiel von vorn: drei frische
Versuche, drei weitere Motorbewegungen, und wieder kein Befund. Ein
Zustand, der verschwindet, weil der Beobachter seine Frage aendert, ist
kein Zustand (Paragraph 5.79).

**Die Pruefungen, und die erste ist der Fall des Betreibers:**

1. Engine verschiebt ihren Wunsch auf den gemeldeten Wert -> der Merker
   bleibt stehen. **Mit der alten Bedingung faellt dieser Test.**
2. Das Geraet meldet den **zuletzt gesendeten** Wert -> der Merker
   faellt, und nur dann.
3. Das Aufgeben setzt den Merker und schreibt genau **eine** Audit-Zeile;
   der zweite Tick schreibt keine zweite.
4. Die Mail geht einmal je Episode hinaus, nicht bei jedem Tick.
5. Der Dashboard-Zaehler zaehlt genau diese Geraete — und keine
   ausgemusterten (Paragraph 5.58).

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (Paragraph 5.50, lokal
gelaufen).

Paragraph 5.59: alle Zeitpunkte sind **absolute** Werte gegen
``FROZEN_NOW``, und die Uhr steht. Beides zusammen, nicht nur das eine.

Der Redis-Doppelgaenger kommt aus ``test_engine_abgleich`` statt als
zweite Kopie — eine Attrappe, zwei Dateien (Paragraph 5.53).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.business_audit import BusinessAudit
from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    RoomStatus,
)
from heizung.models.global_config import GlobalConfig
from heizung.models.heating_zone import HeatingZone
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import dashboard_aggregates, engine_abgleich, mailer
from heizung.services.mailer import MailResult
from heizung.tasks import engine_tasks
from heizung.tasks.engine_tasks import AUDIT_ABGLEICH_ERSCHOEPFT, _dispatch_downlinks_per_zone
from tests.conftest import purge_test_data_by_prefix
from tests.test_engine_abgleich import _FakeRedis

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "ae-" + 4 hex = 7
PREFIX = "ae"
DEV_EUI_PATTERN = "ae7fcafe%"

FROZEN_NOW = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)

UNTEN, OBEN = 15, 25

pytestmark = pytest.mark.asyncio


class _Postfach:
    """Nimmt Mails an, statt sie zu senden. Zaehlt, was rausgegangen waere."""

    def __init__(self) -> None:
        self.mails: list[tuple[str | None, str, str]] = []

    def __call__(self, *, recipient: str | None, subject: str, body: str) -> MailResult:
        self.mails.append((recipient, subject, body))
        return MailResult(True, None, "Testzustellung")


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    """Ohne Redis sendet der Abgleich **nicht** — ein stiller Lauf waere
    dann kein Beleg, sondern eine fehlende Abhaengigkeit (Paragraph 5.55)."""
    client = _FakeRedis()
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def postfach(monkeypatch: pytest.MonkeyPatch) -> _Postfach:
    """Kein echter SMTP-Versuch, und die Drosselung der Mail ausgeschaltet.

    ``alert_throttle`` haengt an Redis; der Doppelgaenger oben kennt die
    Alarm-Schluessel nicht, deshalb wird ``should_send`` hier direkt
    ersetzt. Was diese Datei prueft, ist die Drosselung **durch die
    Episode** — die zweite Bremse daneben waere nur ein zweiter Grund fuer
    dasselbe Ergebnis und wuerde den Test wertlos machen (Paragraph 5.55).
    """
    kasten = _Postfach()
    monkeypatch.setattr(mailer, "send_mail", kasten)
    monkeypatch.setattr(engine_tasks.alert_throttle, "should_send", lambda *a, **k: True)
    return kasten


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


@pytest.fixture
def mock_send_setpoint(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    aufrufe: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        aufrufe.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return aufrufe


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _zimmer(session: AsyncSession) -> tuple[int, int]:
    """Belegtes Zimmer mit einer Zone. Gibt ``(room_id, zone_id)``."""
    marker = uuid.uuid4().hex[:4]
    zimmertyp = RoomType(
        name=f"{PREFIX}-dz-{marker}",
        default_t_occupied=Decimal("21.0"),
        default_t_vacant=Decimal("18.0"),
        default_t_night=Decimal("19.0"),
        min_temp_celsius=Decimal(UNTEN),
        max_temp_celsius=Decimal(OBEN),
    )
    session.add(zimmertyp)
    await session.flush()
    room = Room(
        number=f"{PREFIX}-{marker}",
        room_type_id=zimmertyp.id,
        status=RoomStatus.OCCUPIED,
    )
    session.add(room)
    await session.flush()
    session.add(
        Occupancy(
            room_id=room.id,
            check_in=FROZEN_NOW - timedelta(hours=14),
            check_out=FROZEN_NOW + timedelta(days=2),
            is_active=True,
        )
    )
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    await session.commit()
    return room.id, zone.id


async def _geraet(
    session: AsyncSession,
    zone_id: int,
    *,
    meldet: int,
    zuletzt_gesendet: int,
    erschoepft_seit: datetime | None = None,
) -> Device:
    """Gesundes Geraet mit Messwert und Vorgeschichte.

    Der letzte Befehl liegt zwei Stunden zurueck — ueber
    ``ABGLEICH_MIN_ABSTAND_S`` (900 s). Der Test soll am **Abgleich**
    haengen, nicht an dieser Frist.
    """
    marker = uuid.uuid4().hex[:8]
    dev = Device(
        dev_eui=f"ae7fcafe{marker}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
        abgleich_erschoepft_seit=erschoepft_seit,
    )
    session.add(dev)
    await session.flush()
    session.add(
        SensorReading(
            time=FROZEN_NOW - timedelta(minutes=5),
            device_id=dev.id,
            temperature=Decimal("23.0"),
            setpoint=Decimal(meldet),
        )
    )
    session.add(
        ControlCommand(
            issued_at=FROZEN_NOW - timedelta(hours=2),
            device_id=dev.id,
            target_setpoint=Decimal(zuletzt_gesendet),
            reason=CommandReason.OCCUPIED_SETPOINT,
            sent_to_gateway_at=FROZEN_NOW - timedelta(hours=2),
        )
    )
    await session.commit()
    return dev


def _verbrauche_alle_versuche(redis: _FakeRedis, dev_eui: str) -> None:
    """Setzt den Zaehler auf ``MAX_VERSUCHE`` — die Lage ist erschoepft.

    Direkt im Doppelgaenger und nicht ueber drei echte Laeufe: die drei
    Versuche selbst sind in ``test_engine_abgleich`` geprueft, hier geht
    es um das, was **danach** gilt.
    """
    redis.store[f"engine:abgleich:versuche:{dev_eui.lower()}"] = str(engine_abgleich.MAX_VERSUCHE)


async def _tick(session: AsyncSession, room_id: int, *, soll: int) -> None:
    await _dispatch_downlinks_per_zone(
        session=session,
        room_id=room_id,
        target_setpoint_c=soll,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )


async def _audit_zeilen(session: AsyncSession, device_id: int) -> list[BusinessAudit]:
    stmt = (
        select(BusinessAudit)
        .where(BusinessAudit.action == AUDIT_ABGLEICH_ERSCHOEPFT)
        .where(BusinessAudit.target_id == device_id)
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# 1. Der Fall Geraet 7 — der Grund fuer diese Aufgabe
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_wunschwechsel_der_engine_beendet_die_lage_nicht(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Geraet haelt 20, Engine will jetzt **auch** 20 — der Merker bleibt.

    **Der Test, der mit der alten Bedingung faellt.** Zuletzt gesendet
    wurde 18, das Geraet hat es nie uebernommen und meldet 20. Verschiebt
    die Engine ihren Wunsch auf 20, dann stimmen Wunsch und Meldung
    ueberein — aber das Geraet hat **nichts bestaetigt**. Es hat sich
    nichts an ihm geaendert, nur an der Frage.
    """
    seit = FROZEN_NOW - timedelta(hours=6)
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id, meldet=20, zuletzt_gesendet=18, erschoepft_seit=seit)
    _verbrauche_alle_versuche(fake_redis, dev.dev_eui)

    await _tick(db_session, room_id, soll=20)

    await db_session.refresh(dev)
    assert dev.abgleich_erschoepft_seit == seit, (
        "Der Merker darf nicht fallen, weil die Engine ihren Wunsch verschoben "
        f"hat — das Geraet hat nie bestaetigt. Stand: {dev.abgleich_erschoepft_seit}"
    )
    # Und der Zaehler bleibt verbraucht: sonst begaenne beim naechsten
    # Wunschwechsel die Runde von drei Motorbewegungen von neuem.
    assert engine_abgleich.versuche(dev.dev_eui) == engine_abgleich.MAX_VERSUCHE
    # Der Downlink hier ist **richtig** und kommt nicht aus dem Abgleich,
    # sondern aus der Hysterese: zuletzt gesendet war 18, gewuenscht sind
    # jetzt 20, Delta 2. Genau dieser Downlink fuehrt in den zweiten Teil
    # des Falls — siehe den Test darunter.
    assert [sp for _, sp in mock_send_setpoint] == [20]


@freeze_time(FROZEN_NOW)
async def test_ein_befehl_auf_den_gehaltenen_wert_ist_keine_bestaetigung(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],  # noqa: ARG001 — hier kein Downlink
) -> None:
    """Der **zweite Teil** des Falls Geraet 7, und der unauffaelligere.

    Lage einen Tick nach dem Test oben: die Hysterese hat die 20
    geschickt, zuletzt gesendet ist jetzt **20**, und das Geraet meldet
    20 — weil es die ganze Zeit 20 hielt. Der Vergleich gegen den
    gesendeten Wert allein wuerde das als Bestaetigung lesen, obwohl sich
    am Geraet nichts geaendert hat.

    Die Pruefung ist deshalb nicht "stimmen die Werte ueberein", sondern
    "hat sich etwas geaendert": der Messwert **vor** dem Befehl stand
    schon auf 20.
    """
    seit = FROZEN_NOW - timedelta(hours=6)
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id, meldet=20, zuletzt_gesendet=20, erschoepft_seit=seit)
    # Ein Messwert **vor** dem Befehl, mit demselben Wert: das Geraet hielt
    # die 20 schon, als der Befehl rausging.
    db_session.add(
        SensorReading(
            time=FROZEN_NOW - timedelta(hours=3),
            device_id=dev.id,
            temperature=Decimal("23.0"),
            setpoint=Decimal(20),
        )
    )
    await db_session.commit()
    _verbrauche_alle_versuche(fake_redis, dev.dev_eui)

    await _tick(db_session, room_id, soll=20)

    await db_session.refresh(dev)
    assert dev.abgleich_erschoepft_seit == seit, (
        "Ein Befehl auf den Wert, den das Geraet ohnehin hielt, belegt keine "
        "Uebernahme — der Merker muss stehen bleiben"
    )
    assert engine_abgleich.versuche(dev.dev_eui) == engine_abgleich.MAX_VERSUCHE


# ---------------------------------------------------------------------------
# 2. Nur eine Bestaetigung beendet sie
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_bestaetigung_des_gesendeten_wertes_beendet_die_lage(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Geraet meldet den **zuletzt gesendeten** Wert -> Merker und Zaehler fallen.

    Die Gegenprobe zum Test oben. Sie belegt, dass dort der fehlende
    Merker-Abbau am Vergleich lag und nicht daran, dass der Abbau
    ueberhaupt nicht mehr stattfindet.

    Dass die Engine inzwischen 21 will, ist dabei gleichgueltig: das
    Geraet nimmt Befehle an, und den neuen Wert holt die Hysterese.
    """
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(
        db_session,
        zone_id,
        meldet=18,
        zuletzt_gesendet=18,
        erschoepft_seit=FROZEN_NOW - timedelta(hours=6),
    )
    # Vor dem Befehl stand das Geraet auf 20 — es hat die 18 also
    # **uebernommen** und nicht nur zufaellig gehalten.
    db_session.add(
        SensorReading(
            time=FROZEN_NOW - timedelta(hours=3),
            device_id=dev.id,
            temperature=Decimal("23.0"),
            setpoint=Decimal(20),
        )
    )
    await db_session.commit()
    _verbrauche_alle_versuche(fake_redis, dev.dev_eui)

    await _tick(db_session, room_id, soll=21)

    await db_session.refresh(dev)
    assert dev.abgleich_erschoepft_seit is None
    assert engine_abgleich.versuche(dev.dev_eui) == 0
    # Der Downlink fuer die 21 kommt aus der Hysterese, nicht aus dem
    # Abgleich — er darf hier stehen und belegt, dass nichts blockiert.
    assert [sp for _, sp in mock_send_setpoint] == [21]


# ---------------------------------------------------------------------------
# 3. Das Aufgeben setzt den Merker, und zwar einmal
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_aufgeben_setzt_den_merker_und_schreibt_eine_audit_zeile(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Drei Versuche verbraucht, Geraet weicht ab -> Merker gesetzt, eine Zeile.

    Der zweite Tick darf **keine** zweite Zeile schreiben: die Lage ist
    dieselbe, und eine zweite Zeile ohne zweite Information macht aus dem
    Audit ein Protokoll (Paragraph 5.79).
    """
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id, meldet=20, zuletzt_gesendet=18)
    _verbrauche_alle_versuche(fake_redis, dev.dev_eui)

    await _tick(db_session, room_id, soll=18)
    await db_session.commit()

    await db_session.refresh(dev)
    assert dev.abgleich_erschoepft_seit == FROZEN_NOW
    zeilen = await _audit_zeilen(db_session, dev.id)
    assert len(zeilen) == 1, f"eine Zeile erwartet, waren {len(zeilen)}"
    # Der **gesendete** Wert gehoert hinein und ist nicht derselbe wie der
    # Wunsch — genau ihr Auseinanderfallen war der Fall Geraet 7.
    assert zeilen[0].new_value["gesendeter_sollwert"] == 18
    assert zeilen[0].new_value["gemeldeter_sollwert"] == 20

    await _tick(db_session, room_id, soll=18)
    await db_session.commit()
    assert len(await _audit_zeilen(db_session, dev.id)) == 1, "keine zweite Zeile"
    assert mock_send_setpoint == []


# ---------------------------------------------------------------------------
# 4. Die Mail, einmal je Episode
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_mail_geht_einmal_je_episode(
    db_session: AsyncSession,
    fake_redis: _FakeRedis,
    postfach: _Postfach,
    mock_send_setpoint: list[tuple[str, int]],  # noqa: ARG001 — kein Downlink erwartet
) -> None:
    """Erster Tick: eine Mail. Zweiter Tick, gleiche Lage: keine zweite.

    Die Drosselung ist hier **die Episode selbst**, nicht die Uhr —
    ``alert_throttle.should_send`` ist in dieser Datei auf "immer ja"
    gesetzt. Faellt der Merker-Pfad, faellt dieser Test.
    """
    gc = await db_session.get(GlobalConfig, 1)
    assert gc is not None, "global_config-Singleton fehlt"
    vorher = gc.alert_email
    gc.alert_email = "chef@example.com"
    await db_session.commit()
    try:
        room_id, zone_id = await _zimmer(db_session)
        dev = await _geraet(db_session, zone_id, meldet=20, zuletzt_gesendet=18)
        _verbrauche_alle_versuche(fake_redis, dev.dev_eui)

        await _tick(db_session, room_id, soll=18)
        await db_session.commit()
        assert len(postfach.mails) == 1, f"eine Mail erwartet, waren {len(postfach.mails)}"
        empfaenger, betreff, text = postfach.mails[0]
        assert empfaenger == "chef@example.com"
        assert "nimmt keine Befehle an" in betreff
        # Der Text muss den gesendeten Wert nennen. Ohne ihn liest sich die
        # Mail als "Geraet weicht vom Wunsch ab" — und das war die Lesart,
        # die den Befund an Geraet 7 verschwinden liess.
        assert "Zuletzt gesendet:        18 C" in text

        await _tick(db_session, room_id, soll=18)
        await db_session.commit()
        assert len(postfach.mails) == 1, "keine zweite Mail fuer dieselbe Episode"
    finally:
        gc2 = await db_session.get(GlobalConfig, 1)
        if gc2 is not None:
            gc2.alert_email = vorher
            await db_session.commit()


# ---------------------------------------------------------------------------
# 5. Der Zaehler fuer das Dashboard
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_zaehler_zaehlt_die_lage_und_keine_ausgemusterten(
    db_session: AsyncSession,
) -> None:
    """``count_befehle_nicht_angenommen``: nur aktive Geraete mit Merker.

    Der Lifecycle-Filter ist kein Beiwerk (Paragraph 5.58): ein
    ausgemustertes Geraet liegt im Karton und nimmt deshalb keine Befehle
    an. Es in der Kachel zu zaehlen waere eine Warnung, die niemand
    abstellen kann — und eine Warnung, die immer leuchtet, warnt nicht.
    """
    _, zone_id = await _zimmer(db_session)
    vorher = await dashboard_aggregates.count_befehle_nicht_angenommen(db_session)

    await _geraet(
        db_session,
        zone_id,
        meldet=20,
        zuletzt_gesendet=18,
        erschoepft_seit=FROZEN_NOW - timedelta(hours=2),
    )
    await _geraet(db_session, zone_id, meldet=18, zuletzt_gesendet=18)
    ausgemustert = await _geraet(
        db_session,
        zone_id,
        meldet=20,
        zuletzt_gesendet=18,
        erschoepft_seit=FROZEN_NOW - timedelta(hours=2),
    )
    ausgemustert.retired_at = FROZEN_NOW - timedelta(days=1)
    await db_session.commit()

    assert await dashboard_aggregates.count_befehle_nicht_angenommen(db_session) == vorher + 1
