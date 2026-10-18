"""Bad-Zonen folgen dem Raumtyp „Bad" (18.10.2026).

Fünf Prüfungen, und die zweite ist die wichtigste:

1. **Die Vorlage wirkt:** nachts bekommt die Bad-Zone 22, das
   Schlafzimmer 19 — der Test aus dem Auftrag des Betreibers.
2. **Kein Ping-Pong mit dem Engine-Abgleich** (20f T3): ein Bad-Gerät,
   das 22 meldet, bei Zimmerwert 21 und Bad-Ziel 22, bekommt **keinen**
   Downlink. Ohne diese Prüfung wäre der Fehler lautlos und teuer: der
   Abgleich sendet 21, der Dispatch 22, und das alle 15 Minuten an jedes
   Bad — Motorbewegung und Batterie für nichts (§0 S4).
3. **Ohne Vorlage bleibt alles wie vorher** — ein Haus ohne eigenen
   Bad-Raumtyp ist ein zulässiger Zustand.
4. **Zimmerweite Entscheidungen gewinnen:** eine Zimmer-Übersteuerung
   zieht das Bad mit.
5. **Die Kette bleibt vollständig:** ein ROOM-Eintrag sticht die Vorlage
   aus.

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).

**Der Name der Vorlage kommt aus den Einstellungen**
(``bad_vorlage_room_type``). Die Tests setzen ihn auf einen Namen mit
Test-Prefix — ein Raumtyp „Bad" in der Test-Datenbank wäre nicht über das
Prefix aufräumbar und würde beim zweiten Lauf an der
``unique``-Bedingung scheitern.

§5.59: die Zeitpunkte in den Fixtures sind **absolute** Werte gegen
``FROZEN_NOW``, nicht ``datetime.now`` — sonst rechnet die Fixture in
Echtzeit und der Test fällt am nächsten Tag.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from freezegun import freeze_time
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
    RoomStatus,
    RuleConfigScope,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import evaluate_room
from heizung.tasks.engine_tasks import _dispatch_downlinks_per_zone
from tests.conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "bad-" + 4 hex + 1 = 9
PREFIX = "bad"
DEV_EUI_PATTERN = "deadbeef%"
VORLAGE_NAME = "bad-vorlage-test"

#: Nacht: 23:30 Ortszeit (Europe/Vienna) = 22:30 UTC im Winter.
FROZEN_NOW = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _vorlage_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAD_VORLAGE_ROOM_TYPE", VORLAGE_NAME)
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
def mock_send_setpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, int]]:
    """Sammelt jeden Downlink als ``(dev_eui, setpoint_c)``."""
    aufrufe: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        aufrufe.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return aufrufe


# ---------------------------------------------------------------------------
# Setup-Helfer
# ---------------------------------------------------------------------------


async def _aufbau(
    session: AsyncSession,
    *,
    mit_vorlage: bool = True,
    bad_nacht: float = 22.0,
    zimmer_nacht: float = 19.0,
) -> tuple[int, int, int]:
    """Doppelzimmer mit Schlafzimmer- und Bad-Zone, belegt, Nachtfenster.

    Gibt ``(room_id, schlafzimmer_zone_id, bad_zone_id)``.
    """
    marker = uuid.uuid4().hex[:4]
    zimmertyp = RoomType(
        name=f"{PREFIX}-dz-{marker}",
        default_t_occupied=Decimal("21.0"),
        default_t_vacant=Decimal("18.0"),
        default_t_night=Decimal(str(zimmer_nacht)),
        min_temp_celsius=Decimal("16.0"),
        max_temp_celsius=Decimal("24.0"),
    )
    session.add(zimmertyp)
    if mit_vorlage:
        session.add(
            RoomType(
                name=VORLAGE_NAME,
                default_t_occupied=Decimal("22.0"),
                default_t_vacant=Decimal("18.0"),
                default_t_night=Decimal(str(bad_nacht)),
                min_temp_celsius=Decimal("18.0"),
                max_temp_celsius=Decimal("25.0"),
            )
        )
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
            check_in=FROZEN_NOW - timedelta(hours=6),
            check_out=FROZEN_NOW + timedelta(days=2),
            is_active=True,
        )
    )
    # Nachtfenster am **Zimmer**, nicht global.
    #
    # Zwei Gruende, beide aus einem roten Lauf gelernt: eine GLOBAL-Zeile
    # waere vom Prefix-Cleanup nicht erfasst (es raeumt Zimmer und
    # Raumtypen) und blieb in der Test-Datenbank stehen. Und umgekehrt
    # hinterlassen andere Tests ebenfalls GLOBAL-Zeilen — welche davon
    # ``resolve_rule_field`` zuerst sieht, ist nicht definiert. Genau das
    # hat diese Datei in der Gesamt-Suite rot gemacht, allein aber gruen
    # gelassen: ein fremdes ``night_start=00:00`` gewann, das Nachtfenster
    # griff nicht, und der Test sah 21 statt 19.
    #
    # Am ROOM-Scope ist die Zeile eindeutig fuer dieses Zimmer, gewinnt
    # gegen jede fremde GLOBAL-Zeile und verschwindet mit dem Zimmer
    # (CASCADE). §5.39 in anderer Form: nicht die Welt aufraeumen, sondern
    # die eigene Frage so stellen, dass die Welt sie nicht beeinflusst.
    session.add(
        RuleConfig(
            scope=RuleConfigScope.ROOM,
            room_id=room.id,
            night_start=time(22, 0),
            night_end=time(6, 0),
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
    gemeldeter_sollwert: int | None = None,
    zuletzt_gesendet: int | None = None,
    gesendet_vor: timedelta = timedelta(hours=2),
) -> int:
    """Gesundes Geraet in der Zone, optional mit Messwert und Vorgeschichte."""
    marker = uuid.uuid4().hex[:8]
    dev = Device(
        dev_eui=f"deadbeef{marker}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
    )
    session.add(dev)
    await session.flush()
    if gemeldeter_sollwert is not None:
        session.add(
            SensorReading(
                time=FROZEN_NOW - timedelta(minutes=5),
                device_id=dev.id,
                temperature=Decimal("21.0"),
                setpoint=Decimal(str(gemeldeter_sollwert)),
            )
        )
    if zuletzt_gesendet is not None:
        session.add(
            ControlCommand(
                issued_at=FROZEN_NOW - gesendet_vor,
                device_id=dev.id,
                target_setpoint=Decimal(str(zuletzt_gesendet)),
                reason=CommandReason.OCCUPIED_SETPOINT,
                sent_to_gateway_at=FROZEN_NOW - gesendet_vor,
            )
        )
    await session.commit()
    return dev.id


# ---------------------------------------------------------------------------
# 1. Die Vorlage wirkt
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_bad_bekommt_nachts_22_das_zimmer_19(db_session: AsyncSession) -> None:
    room_id, _, _ = await _aufbau(db_session)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 19, "Schlafzimmer: Nachtabsenkung des Zimmertyps"
    assert ergebnis.bad_setpoint_c == 22, "Bad: Nachtwert der Vorlage"


@freeze_time(FROZEN_NOW)
async def test_grenzen_der_vorlage_gelten_fuer_das_bad(db_session: AsyncSession) -> None:
    # Vorlage will nachts 30, ihre Obergrenze ist 25 -> der Clamp der
    # **Vorlage** greift, nicht der des Zimmertyps (24).
    room_id, _, _ = await _aufbau(db_session, bad_nacht=30.0)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.bad_setpoint_c == 25


# ---------------------------------------------------------------------------
# 2. Kein Ping-Pong mit dem Engine-Abgleich (Pflicht aus dem Auftrag)
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_abgleich_sendet_nicht_wenn_das_bad_schon_auf_dem_bad_ziel_steht(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Das Bad meldet 22, Zimmerwert 21, Bad-Ziel 22 -> kein Downlink.

    Ohne den Bad-Wert im Dispatch verglich der Abgleich gegen 21, haette
    gesendet, und der naechste Tick haette wieder 22 geschickt. Der Test
    prueft deshalb **die Abwesenheit** eines Downlinks, nicht seinen Wert.
    """
    room_id, _, bad_zone = await _aufbau(db_session)
    await _geraet(db_session, bad_zone, gemeldeter_sollwert=22, zuletzt_gesendet=22)

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        bad_setpoint_c=22,
    )

    assert mock_send_setpoint == [], f"kein Downlink erwartet, war: {mock_send_setpoint}"
    bad_status = next(z for z in pro_zone if z["zone_id"] == bad_zone)
    assert bad_status["count_sent"] == 0


@freeze_time(FROZEN_NOW)
async def test_ohne_bad_wert_wuerde_der_abgleich_senden(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    """Die Gegenprobe: derselbe Aufbau ohne Bad-Ziel sendet 21.

    Sie haelt fest, dass der Test oben nicht aus einem anderen Grund still
    ist (abgeschaltete Hysterese, fehlendes Geraet) — ohne diese
    Gegenprobe waere die Abwesenheit eines Downlinks kein Beleg
    (§5.55-Familie).
    """
    room_id, _, bad_zone = await _aufbau(db_session)
    await _geraet(db_session, bad_zone, gemeldeter_sollwert=22, zuletzt_gesendet=22)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.OCCUPIED_SETPOINT,
        eval_id=uuid.uuid4(),
        bad_setpoint_c=None,
    )

    assert [sp for _, sp in mock_send_setpoint] == [21]


@freeze_time(FROZEN_NOW)
async def test_schlafzimmer_bekommt_weiter_den_zimmerwert(
    db_session: AsyncSession,
    mock_send_setpoint: list[tuple[str, int]],
) -> None:
    room_id, schlaf_zone, _ = await _aufbau(db_session)
    await _geraet(db_session, schlaf_zone, gemeldeter_sollwert=22, zuletzt_gesendet=22)

    await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=19,
        base_reason=CommandReason.NIGHT_SETBACK,
        eval_id=uuid.uuid4(),
        bad_setpoint_c=22,
    )

    assert [sp for _, sp in mock_send_setpoint] == [19], "Bad-Wert darf nicht abfaerben"


# ---------------------------------------------------------------------------
# 3. Ohne Vorlage wie vorher
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_ohne_vorlage_folgt_das_bad_dem_zimmer(db_session: AsyncSession) -> None:
    room_id, _, _ = await _aufbau(db_session, mit_vorlage=False)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 19
    assert ergebnis.bad_setpoint_c is None


@freeze_time(FROZEN_NOW)
async def test_leerer_name_schaltet_die_vorlage_ab(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    room_id, _, _ = await _aufbau(db_session)
    monkeypatch.setenv("BAD_VORLAGE_ROOM_TYPE", "")
    get_settings.cache_clear()

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.bad_setpoint_c is None


# ---------------------------------------------------------------------------
# 4. Zimmerweite Entscheidungen gewinnen
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_zimmer_uebersteuerung_zieht_das_bad_mit(db_session: AsyncSession) -> None:
    """Eine Wahl fuer das ganze Zimmer gilt auch im Bad.

    Der Gast hat 20 fuer das Zimmer gesetzt — dann heizt das Bad nicht
    weiter auf 22, nur weil es ein Bad ist.
    """
    room_id, _, _ = await _aufbau(db_session)
    db_session.add(
        ManualOverride(
            room_id=room_id,
            heating_zone_id=None,
            setpoint=Decimal("20.0"),
            source=OverrideSource.FRONTEND_4H,
            expires_at=FROZEN_NOW + timedelta(hours=4),
        )
    )
    await db_session.commit()

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 20
    assert ergebnis.bad_setpoint_c is None, "Bad folgt dem Zimmerwert"


# ---------------------------------------------------------------------------
# 5. Die Kette bleibt vollstaendig
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_zimmer_eintrag_sticht_die_vorlage_aus(db_session: AsyncSession) -> None:
    """Ein ROOM-Eintrag gewinnt gegen ROOM_TYPE(Vorlage) — auch fuers Bad.

    Das ist die Zusage aus dem Plan: die Vorlage sitzt in der Kette an der
    Stelle des Raumtyps, nicht davor. Der Wert liegt hier innerhalb der
    Bad-Grenzen (18/25), damit der Test die **Kette** prueft und nicht den
    Clamp — dafuer gibt es den naechsten Test.
    """
    room_id, _, _ = await _aufbau(db_session)
    db_session.add(
        RuleConfig(
            scope=RuleConfigScope.ROOM,
            room_id=room_id,
            t_night=Decimal("20.0"),
        )
    )
    await db_session.commit()

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 20
    assert ergebnis.bad_setpoint_c == 20, "ROOM gewinnt auch im Bad-Durchlauf"


@freeze_time(FROZEN_NOW)
async def test_untergrenze_der_vorlage_haelt_gegen_den_zimmer_eintrag(
    db_session: AsyncSession,
) -> None:
    """Die Kette gewinnt, die Grenzen der Vorlage halten trotzdem.

    Ein ROOM-Eintrag mit 17 zieht das **Zimmer** auf 17 — das Bad bleibt
    bei **18**, seiner Untergrenze. Das ist gewollt: der Betreiber hat die
    Grenzen 18/25 fuer Baeder gesetzt, und eine Grenze, die eine
    Einstellung aussticht, ist der Zweck einer Grenze.

    Dieser Test ist aus einer falschen Erwartung von mir entstanden: ich
    hatte hier 17 erwartet und 18 bekommen. Der Code hatte recht, die
    Zusicherung nicht — deshalb steht die Wechselwirkung jetzt als eigener
    Test da und nicht als Fussnote.
    """
    room_id, _, _ = await _aufbau(db_session)
    db_session.add(
        RuleConfig(
            scope=RuleConfigScope.ROOM,
            room_id=room_id,
            t_night=Decimal("17.0"),
        )
    )
    await db_session.commit()

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 17, "Zimmer: Zimmertyp-Untergrenze ist 16"
    assert ergebnis.bad_setpoint_c == 18, "Bad: Untergrenze der Vorlage"


@freeze_time(FROZEN_NOW)
async def test_hausweiter_nachtwert_sticht_die_vorlage_nicht_aus(
    db_session: AsyncSession,
) -> None:
    """Eine GLOBAL-Zeile mit ``t_night`` darf das Bad nicht herunterziehen.

    **Der Wächter für den Befund vom 18.10.2026.** Die Spalten eines
    Raumtyps (``default_t_*``) sind in der Auflösung der letzte Rückfall —
    *unter* GLOBAL. Ohne Gegenmaßnahme bekäme das Bad also die
    Nachtabsenkung des Hauses (19) statt seiner eigenen (22), und zwar
    genau für das Feld, um das es dem Betreiber geht.
    Deshalb treten die Spalten der Vorlage als ihre eigenen
    ROOM_TYPE-Werte auf (``engine._bad_zielwert``).

    Aufgefallen ist der Fall **nicht** in diesem Test, sondern daran, dass
    die Datei in der Gesamt-Suite rot war und allein grün — eine fremde
    GLOBAL-Zeile aus einem anderen Test hatte gewonnen. Die Mutationsprobe
    hat dann gezeigt, dass es dafür keinen Wächter gab: Vorrang-Zeile
    entfernt, alles grün. Diesen Wächter.

    Die GLOBAL-Zeile wird hier **selbst** angelegt und im ``finally``
    wieder entfernt — das Prefix-Cleanup erfasst sie nicht (es räumt
    Zimmer und Raumtypen), und stehenbleiben darf sie nicht: sie würde
    andere Tests beeinflussen, so wie sie diesen beeinflusst hat.
    """
    room_id, _, _ = await _aufbau(db_session)
    hausweit = RuleConfig(scope=RuleConfigScope.GLOBAL, t_night=Decimal("19.0"))
    db_session.add(hausweit)
    await db_session.commit()
    try:
        ergebnis = await evaluate_room(db_session, room_id)

        assert ergebnis is not None
        assert ergebnis.setpoint_c == 19, "Zimmer: hausweite Nachtabsenkung gilt"
        assert ergebnis.bad_setpoint_c == 22, "Bad: eigener Wert der Vorlage"
    finally:
        await db_session.delete(hausweit)
        await db_session.commit()


# ---------------------------------------------------------------------------
# 6. Die Zimmerseite zeigt den Bad-Wert
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_zonen_karte_zeigt_den_bad_wert(db_session: AsyncSession) -> None:
    """``HeatingZoneRead.engine_setpoint_c`` je Zone, nicht je Zimmer.

    Ohne diesen Weg zeigte die Bad-Karte 19, waehrend das Geraet 22 fuhr —
    die Zimmerseite waere die zweite Wahrheit zur Engine (§5.53).

    Der Wert kommt aus derselben ``HARD_CLAMP``-Zeile wie der Zimmerwert
    (``details->>'bad_setpoint_c'``), damit beide nicht aus verschiedenen
    Auswertungen stammen koennen.
    """
    from heizung.api.v1.heating_zones import _build_zone_read
    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog
    from heizung.models.heating_zone import HeatingZone as _Zone

    room_id, schlaf_zone, bad_zone = await _aufbau(db_session)
    db_session.add(
        EventLog(
            time=FROZEN_NOW - timedelta(minutes=1),
            room_id=room_id,
            evaluation_id=uuid.uuid4(),
            layer=EventLogLayer.HARD_CLAMP,
            setpoint_in=Decimal("19.0"),
            setpoint_out=Decimal("19.0"),
            reason=CommandReason.NIGHT_SETBACK,
            details={"detail": "test", "bad_setpoint_c": 22},
        )
    )
    await db_session.commit()

    schlaf = await db_session.get(_Zone, schlaf_zone)
    bad = await db_session.get(_Zone, bad_zone)
    assert schlaf is not None and bad is not None

    schlaf_read = await _build_zone_read(db_session, schlaf)
    bad_read = await _build_zone_read(db_session, bad)

    assert schlaf_read.engine_setpoint_c == Decimal("19.0")
    assert bad_read.engine_setpoint_c == Decimal(22)


@freeze_time(FROZEN_NOW)
async def test_zonen_karte_ohne_bad_wert_zeigt_den_zimmerwert(
    db_session: AsyncSession,
) -> None:
    """``bad_setpoint_c: None`` heisst "Bad folgt dem Zimmer" — auch in der
    Anzeige. Das ist der Fall nach einer Uebersteuerung oder bei offenem
    Fenster."""
    from heizung.api.v1.heating_zones import _build_zone_read
    from heizung.models.enums import EventLogLayer
    from heizung.models.event_log import EventLog
    from heizung.models.heating_zone import HeatingZone as _Zone

    room_id, _, bad_zone = await _aufbau(db_session)
    db_session.add(
        EventLog(
            time=FROZEN_NOW - timedelta(minutes=1),
            room_id=room_id,
            evaluation_id=uuid.uuid4(),
            layer=EventLogLayer.HARD_CLAMP,
            setpoint_in=Decimal("8.0"),
            setpoint_out=Decimal("8.0"),
            reason=CommandReason.WINDOW_OPEN,
            details={"detail": "window_open", "bad_setpoint_c": None},
        )
    )
    await db_session.commit()

    bad = await db_session.get(_Zone, bad_zone)
    assert bad is not None
    bad_read = await _build_zone_read(db_session, bad)

    assert bad_read.engine_setpoint_c == Decimal("8.0"), "Fenster gilt im Bad genauso"
