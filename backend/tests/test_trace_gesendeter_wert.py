"""Der Trace nennt den gesendeten Wert je Geraet und die Zonen-Uebersteuerung (Sprint 25, T4).

**Warum das im selben Sprint wie das Entprellen steht.** T1 aendert,
*was* gesendet wird. Ein Trace, der das nicht zeigt, macht die Abnahme
von T1 unmoeglich — man koennte nicht unterscheiden, ob das Entprellen
gewirkt hat oder ob ein Befehl verloren ging. Eine Pruefung fuer beides.

**Zwei Dinge, und bei beiden war die Lage anders als im Brief
angenommen** — Einzelheiten im PR-Text:

1. ``setpoint_c`` je Geraet steht **schon** im Trace (seit dem
   31.10.2026). Was fehlte, ist die Unterscheidung zwischen *Absicht* und
   *tatsaechlich hinausgegangen*: ``gesendet_c``. Heute sind beide gleich;
   nach T1 koennen sie abweichen, und dann ist das die einzige Stelle, an
   der sich "entprellt" von "verloren" unterscheiden laesst.
2. „no active override" bei einer **zonen**-weiten Uebersteuerung ist in
   der **Oberflaeche** seit Sprint 12b T4 bereits richtig aufgeloest.
   Falsch war allein die **gespeicherte** Zeile im ``event_log``.

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (Paragraph 5.50, lokal
gelaufen).

Paragraph 5.59: absolute Zeitpunkte gegen ``FROZEN_NOW``, und die Uhr
steht.
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import (
    CommandReason,
    DeviceKind,
    DeviceVendor,
    EventLogLayer,
    HeatingZoneKind,
    OverrideSource,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import evaluate_room
from heizung.services import engine_abgleich
from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone
from tests.conftest import purge_test_data_by_prefix
from tests.test_engine_abgleich import _FakeRedis

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "tr-" + 4 hex = 7
PREFIX = "tr"
DEV_EUI_PATTERN = "7acefeed%"

FROZEN_NOW = datetime(2026, 11, 8, 10, 0, tzinfo=UTC)
UNTEN, OBEN = 15, 25

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: client)
    return client


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
def gesendete_werte(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Faengt ab, **was wirklich an den Downlink uebergeben wurde**.

    Der Punkt dieser Attrappe: ``gesendet_c`` im Trace darf nicht aus
    derselben Variablen stammen wie die Behauptung darueber, sonst prueft
    der Test eine Zuweisung gegen sich selbst (Paragraph 5.55).
    """
    aufrufe: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        aufrufe.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return aufrufe


@pytest.fixture
def downlink_faellt_aus(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        raise TimeoutError("Gateway antwortet nicht")

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _zimmer_mit_zwei_zonen(session: AsyncSession) -> tuple[int, int, int]:
    """Zimmer mit Schlafzimmer- und Bad-Zone. Gibt ``(room_id, schlaf, bad)``."""
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
    schlaf = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    bad = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BATHROOM, name="Bad")
    session.add_all([schlaf, bad])
    await session.flush()
    await session.commit()
    return room.id, schlaf.id, bad.id


async def _geraet(
    session: AsyncSession,
    zone_id: int,
    *,
    meldet: int,
    zuletzt_gesendet: int | None = None,
) -> Device:
    marker = uuid.uuid4().hex[:8]
    dev = Device(
        dev_eui=f"7acefeed{marker}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    session.add(
        SensorReading(
            time=FROZEN_NOW - timedelta(minutes=5),
            device_id=dev.id,
            temperature=Decimal("22.0"),
            setpoint=Decimal(meldet),
        )
    )
    if zuletzt_gesendet is not None:
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


# ---------------------------------------------------------------------------
# 1. gesendet_c
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_gesendet_c_traegt_den_wert_des_downlinks(
    db_session: AsyncSession,
    gesendete_werte: list[tuple[str, int]],
) -> None:
    """Der Wert im Trace ist der Wert, der an den Downlink ging.

    Geprueft gegen die **Attrappe**, nicht gegen die Zielvariable: sonst
    waere es eine Zuweisung, die sich selbst bestaetigt.
    """
    room_id, schlaf, _bad = await _zimmer_mit_zwei_zonen(db_session)
    dev = await _geraet(db_session, schlaf, meldet=18, zuletzt_gesendet=18)

    pro_geraet, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    zeile = next(z for z in pro_geraet if z["device_id"] == dev.id)
    assert zeile["status"] == "sent"
    assert gesendete_werte == [(dev.dev_eui, 21)]
    assert zeile["gesendet_c"] == gesendete_werte[0][1]
    # Die Absicht steht weiter daneben und ist heute dieselbe Zahl. Nach
    # T1 koennen sie abweichen — dann ist das der Unterschied zwischen
    # "entprellt" und "verloren".
    assert zeile["setpoint_c"] == 21


@freeze_time(FROZEN_NOW)
async def test_ohne_downlink_steht_kein_gesendeter_wert(
    db_session: AsyncSession,
    gesendete_werte: list[tuple[str, int]],
) -> None:
    """Hysterese schweigt -> ``gesendet_c`` ist ``None``, nicht der Zielwert.

    Eine Zahl an dieser Stelle liest sich als gesendet. Genau diese
    Verwechslung soll das Feld verhindern.
    """
    room_id, schlaf, _bad = await _zimmer_mit_zwei_zonen(db_session)
    dev = await _geraet(db_session, schlaf, meldet=21, zuletzt_gesendet=21)

    pro_geraet, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    zeile = next(z for z in pro_geraet if z["device_id"] == dev.id)
    assert zeile["status"] == "skipped_hysteresis"
    assert zeile["gesendet_c"] is None
    assert zeile["setpoint_c"] == 21
    assert gesendete_werte == []


@freeze_time(FROZEN_NOW)
async def test_fehlgeschlagener_downlink_traegt_keinen_gesendeten_wert(
    db_session: AsyncSession,
    downlink_faellt_aus: None,  # noqa: ARG001 — Attrappe wirkt ueber monkeypatch
) -> None:
    """Der Publish wirft -> beim Gateway ist nichts angekommen.

    Das ist der Fall, in dem die beiden Felder sich **heute schon**
    unterscheiden: ``setpoint_c`` nennt die Absicht, ``gesendet_c`` ist
    ``None``.
    """
    room_id, schlaf, _bad = await _zimmer_mit_zwei_zonen(db_session)
    dev = await _geraet(db_session, schlaf, meldet=18, zuletzt_gesendet=18)

    pro_geraet, _ = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        clamp_grenzen_c=(UNTEN, OBEN),
    )

    zeile = next(z for z in pro_geraet if z["device_id"] == dev.id)
    assert zeile["status"] == "failed"
    assert zeile["gesendet_c"] is None
    assert zeile["setpoint_c"] == 21
    assert "TimeoutError" in zeile["error"]


# ---------------------------------------------------------------------------
# 2. Die Schicht manual_override benennt die Zonen-Uebersteuerung
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_zonen_uebersteuerung_wird_in_der_schicht_benannt(
    db_session: AsyncSession,
) -> None:
    """Nur das Bad ist uebersteuert -> die Zeile sagt das, statt „no active override".

    Der Wert selbst bleibt unberuehrt: ``setpoint_c`` der Schicht ist
    weiter der durchgereichte Zimmerwert, und ``extras["source"]`` bleibt
    ``None`` — zimmerweit ist gerade **nicht** eingegriffen worden, und an
    dieser Angabe haengt die Bad-Vorlage.
    """
    room_id, _schlaf, bad = await _zimmer_mit_zwei_zonen(db_session)
    db_session.add(
        ManualOverride(
            room_id=room_id,
            heating_zone_id=bad,
            setpoint=Decimal(23),
            source=OverrideSource.FRONTEND_24H,
            expires_at=FROZEN_NOW + timedelta(hours=4),
        )
    )
    await db_session.commit()

    ergebnis = await evaluate_room(db_session, room_id)

    schicht = next(s for s in ergebnis.layers if s.layer == EventLogLayer.MANUAL_OVERRIDE)
    assert "no active override" not in (schicht.detail or "")
    assert "keine zimmerweite Uebersteuerung" in (schicht.detail or "")
    assert f"{bad}=23" in (schicht.detail or "")
    extras = schicht.extras or {}
    assert extras["zonen_uebersteuerungen"] == [{"zone_id": bad, "setpoint_c": 23}]
    # Unberuehrt, und beides mit Grund.
    assert extras["source"] is None
    assert ergebnis.zone_overrides[bad] == 23


@freeze_time(FROZEN_NOW)
async def test_ohne_jede_uebersteuerung_bleibt_die_zeile_wie_sie_war(
    db_session: AsyncSession,
) -> None:
    """Die Gegenprobe: kein Override -> „no active override" ist richtig.

    Ohne sie koennte die Aenderung oben jede Zeile umschreiben, und der
    Trace wuerde eine Uebersteuerung behaupten, wo keine ist.
    """
    room_id, _schlaf, _bad = await _zimmer_mit_zwei_zonen(db_session)

    ergebnis = await evaluate_room(db_session, room_id)

    schicht = next(s for s in ergebnis.layers if s.layer == EventLogLayer.MANUAL_OVERRIDE)
    assert schicht.detail == "no active override"
    assert "zonen_uebersteuerungen" not in (schicht.extras or {})


@freeze_time(FROZEN_NOW)
async def test_zimmerweite_uebersteuerung_bleibt_die_zimmerweite_zeile(
    db_session: AsyncSession,
) -> None:
    """Zimmerweiter Override -> die Zeile nennt ihn, nicht die Zonen.

    ``get_active`` liefert einen zimmerweiten Override auch fuer eine
    Zonen-Abfrage; der Zonen-Filter in ``evaluate_room`` sortiert ihn aus
    (``heating_zone_id == zone.id``). Dieser Test haelt fest, dass der
    neue Zweig daran nichts aendert — sonst stuende in der Zeile zweimal
    dasselbe, einmal als Zimmer- und einmal als Zonenwert.
    """
    room_id, _schlaf, _bad = await _zimmer_mit_zwei_zonen(db_session)
    db_session.add(
        ManualOverride(
            room_id=room_id,
            setpoint=Decimal(22),
            source=OverrideSource.FRONTEND_24H,
            expires_at=FROZEN_NOW + timedelta(hours=4),
        )
    )
    await db_session.commit()

    ergebnis = await evaluate_room(db_session, room_id)

    schicht = next(s for s in ergebnis.layers if s.layer == EventLogLayer.MANUAL_OVERRIDE)
    assert "source=frontend_24h" in (schicht.detail or "")
    assert "zonen_uebersteuerungen" not in (schicht.extras or {})
    assert ergebnis.zone_overrides == {}
