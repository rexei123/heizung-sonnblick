"""Die Engine schickt keinem Relais einen Sollwert (2d, 14.11.2026).

**Der Befund.** Seit dem 01.11.2026 hingen zwei 16ASPM-Relais in Zonen,
und die Engine behandelte sie wie Thermostate: `_get_zone_devices`
filterte `retired_at`, `health_state` und `measure_only` — nach der
**Geräteart** fragte niemand. Gemessen am 14.11. in der Produktion:
**51 `0x51`-Befehle** an die zwei Relais (Rezeption 16, Bar 35), alle
`sent_to_gateway_at` gesetzt, **keiner** bestätigt. Fünfzehn davon in den
letzten 24 Stunden.

Ein 16ASPM ist ein Schalter. Er hat kein Sollwert-Register, kennt `0x51`
nicht und verwirft den Befehl. Jeder dieser Downlinks war Sendezeit,
ein Eintrag in der ChirpStack-Warteschlange und eine Zeile in
`control_command` — ohne jede Wirkung am Gerät.

**Was den Schaden begrenzt hat**, und zwar zufällig: der Abgleich
(Sprint 20f) vergleicht den gemeldeten Sollwert des Geräts mit dem
gesendeten. Ein Relais meldet keinen, also ist `ist_wert` immer `None`,
und die Nachsende-Schleife konnte nicht anlaufen. Ohne diese Eigenschaft
hätte jedes Relais zusätzlich die Abgleich-Wiederholungen bekommen.

Geschaltet wird ein Relais vom Relais-Orchestrator (`tasks/relay_tasks`),
und zwar aus dem **Ergebnis** dieser Engine: der Sollwert der Zone steht
im `HARD_CLAMP`-Trace. Deshalb prüft diese Datei beides — dass nichts
mehr an das Relais geht **und** dass der Sollwert weiter im Trace landet.
Das zweite ist die wichtigere Hälfte: eine Änderung, die den Steuerpfad
des Relais kappt, wäre schlimmer als der Fehler, den sie behebt.

DB-Tests, skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.tasks.engine_tasks import (
    _dispatch_downlinks_per_zone,
    _get_zone_devices,
    _zone_hat_nur_relais,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t2dr"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def gesendet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Sammelt jeden Sollwert-Downlink als ``(dev_eui, setpoint_c)``."""
    aufrufe: list[tuple[str, int]] = []

    async def _mock(dev_eui: str, setpoint_c: int) -> str:
        aufrufe.append((dev_eui, setpoint_c))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr("heizung.tasks.engine_tasks.send_setpoint", _mock)
    return aufrufe


async def _zimmer(session: AsyncSession, *, marker: str) -> tuple[int, int]:
    """Ein nicht buchbares Zimmer mit einer Zone. ``Room.number`` ist
    ``VARCHAR(20)`` (§5.49): Prefix (4) + Marker (<= 4) + 4 Hex = 14.
    """
    short = uuid.uuid4().hex[:4]
    rt = RoomType(
        name=f"{PREFIX}-rt-{marker}-{short}",
        is_bookable=False,
        default_t_occupied=Decimal("21.0"),
    )
    session.add(rt)
    await session.flush()
    room = Room(number=f"{PREFIX}-{marker}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Barbereich")
    session.add(zone)
    await session.flush()
    return room.id, zone.id


async def _geraet(session: AsyncSession, zone_id: int, *, kind: DeviceKind, label: str) -> Device:
    jetzt = datetime.now(tz=UTC)
    ist_relais = kind == DeviceKind.RELAY
    dev = Device(
        dev_eui=f"beef{uuid.uuid4().hex[:12]}",
        kind=kind,
        vendor=DeviceVendor.MCLIMATE,
        model="16ASPM" if ist_relais else "vicki",
        label=label,
        heating_zone_id=zone_id,
        health_state="healthy",
        # In Betrieb genommen (S3) — ein Relais, das gar nicht schalten
        # darf, wuerde den Test auch ohne den Filter bestehen.
        power_return_verified_at=jetzt - timedelta(hours=2) if ist_relais else None,
        overheating_recovery_verified_at=jetzt - timedelta(hours=2) if ist_relais else None,
        commissioned_at=jetzt - timedelta(hours=1) if ist_relais else None,
    )
    session.add(dev)
    await session.flush()
    return dev


# ---------------------------------------------------------------------------
# Die Auswahl der angesteuerten Geraete
# ---------------------------------------------------------------------------


async def test_relais_wird_nicht_angesteuert(db_session: AsyncSession) -> None:
    """``_get_zone_devices`` laesst ein Relais weg, das Thermostat nicht.

    Die Stelle, die Mutationsprobe M7 angreift — dieselbe Zeile, die schon
    ``measure_only`` filtert.
    """
    _, zone_id = await _zimmer(db_session, marker="mix")
    ventil = await _geraet(db_session, zone_id, kind=DeviceKind.THERMOSTAT, label="Ventil")
    relais = await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    angesteuert = await _get_zone_devices(db_session, zone_id)

    ids = {d.id for d in angesteuert}
    assert ventil.id in ids, "ein Thermostat wird weiter angesteuert"
    assert relais.id not in ids, "ein Relais bekommt keinen Sollwert"


async def test_zone_nur_mit_relais_wird_gar_nicht_angesteuert(
    db_session: AsyncSession,
) -> None:
    """Der Fall Rezeption und Bar: in der Zone haengt nur das Panel."""
    _, zone_id = await _zimmer(db_session, marker="only")
    await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    assert await _get_zone_devices(db_session, zone_id) == []


async def test_das_relais_bleibt_in_der_zone(db_session: AsyncSession) -> None:
    """**Die Vorgabe des Betreibers, und sie ist das Gegenteil des Filters.**

    Nicht angesteuert heisst nicht entfernt. Die Zone ist der Ort, an dem
    Soll, Ist und Schaltzustand zusammenkommen; ohne Zone findet der
    Orchestrator das Relais nicht, der Melder aus #403 ebenso wenig, und
    die Anzeige zeigt ein Zimmer ohne Heizung.
    """
    _, zone_id = await _zimmer(db_session, marker="bleib")
    relais = await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    from heizung.services.device_service import get_active_devices_for_zone

    in_der_zone = await get_active_devices_for_zone(db_session, zone_id)

    assert [d.id for d in in_der_zone] == [relais.id]
    assert relais.heating_zone_id == zone_id


# ---------------------------------------------------------------------------
# Der Dispatch
# ---------------------------------------------------------------------------


async def test_dispatch_schickt_dem_relais_nichts_und_schreibt_keine_zeile(
    db_session: AsyncSession, gesendet: list[tuple[str, int]]
) -> None:
    """**Die Gegenprobe zu den 51 Zeilen vom 14.11.**

    Kein Downlink und keine ``control_command``-Zeile. Die zweite Haelfte
    ist die, die man spaeter sieht: eine Zeile ohne Bestaetigung sieht aus
    wie ein Funkproblem, und am Relais 109 gab es eines — nur hat es mit
    diesen Zeilen nichts zu tun.
    """
    room_id, zone_id = await _zimmer(db_session, marker="disp")
    relais = await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    assert gesendet == [], f"kein Sollwert an ein Relais, war: {gesendet}"
    zeilen = (
        (
            await db_session.execute(
                select(ControlCommand).where(ControlCommand.device_id == relais.id)
            )
        )
        .scalars()
        .all()
    )
    assert list(zeilen) == [], "und keine Zeile, die eine Bestaetigung vermissen koennte"
    status = next(z for z in pro_zone if z["zone_id"] == zone_id)
    assert status["count_sent"] == 0
    assert status["count_failed"] == 0


async def test_der_sollwert_der_zone_steht_trotzdem_im_trace(
    db_session: AsyncSession, gesendet: list[tuple[str, int]]
) -> None:
    """**Die wichtigere Haelfte: der Steuerpfad des Relais bleibt heil.**

    Der Orchestrator liest den Sollwert nicht aus ``control_command``,
    sondern aus dem ``HARD_CLAMP``-Trace. Steht dort nichts, sagt er
    ``kein_engine_soll`` und schaltet gar nicht — aus einem Panel, das
    einen Befehl zu viel bekam, wuerde eines, das keinen mehr bekommt.
    """
    room_id, zone_id = await _zimmer(db_session, marker="soll")
    await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    status = next(z for z in pro_zone if z["zone_id"] == zone_id)
    assert status["setpoint_c"] == 21, "ohne diese Zahl regelt das Relais nicht mehr"


async def test_der_grund_im_trace_nennt_das_relais(
    db_session: AsyncSession, gesendet: list[tuple[str, int]]
) -> None:
    """``nur_relais_in_der_zone`` statt ``no_healthy_active_devices``.

    Der alte Grund behauptete, die Zone habe kein gesundes Geraet —
    waehrend ein gesundes, in Betrieb genommenes Relais darin haengt und
    jede Minute geregelt wird. Wer das im Engine-Panel der Rezeption
    liest, sucht einen Ausfall, den es nicht gibt (§5.79).
    """
    room_id, zone_id = await _zimmer(db_session, marker="grund")
    await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    status = next(z for z in pro_zone if z["zone_id"] == zone_id)
    assert status["detail"] == "nur_relais_in_der_zone"


async def test_eine_leere_zone_heisst_weiter_keine_gesunden_geraete(
    db_session: AsyncSession, gesendet: list[tuple[str, int]]
) -> None:
    """Die Gegenprobe zum Grund: ohne Geraet bleibt der alte Text.

    Sonst stuende an einer Zone ohne jedes Geraet „nur Relais", und der
    neue Grund waere wertlos, weil er nichts unterscheidet.
    """
    room_id, zone_id = await _zimmer(db_session, marker="leer")

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    status = next(z for z in pro_zone if z["zone_id"] == zone_id)
    assert status["detail"] == "no_healthy_active_devices"


async def test_gemischte_zone_meldet_keinen_relais_grund(
    db_session: AsyncSession, gesendet: list[tuple[str, int]]
) -> None:
    """Haengt ein Ventil daneben, laeuft der normale Pfad.

    Der Grund gilt nur fuer eine Zone, in der **ausschliesslich** Relais
    haengen — sonst wuerde eine Zone mit einem stillen Ventil als
    Relais-Zone ausgewiesen.
    """
    room_id, zone_id = await _zimmer(db_session, marker="gem")
    ventil = await _geraet(db_session, zone_id, kind=DeviceKind.THERMOSTAT, label="Ventil")
    await _geraet(db_session, zone_id, kind=DeviceKind.RELAY, label="Panel")

    assert await _zone_hat_nur_relais(db_session, zone_id) is False

    _, pro_zone = await _dispatch_downlinks_per_zone(
        session=db_session,
        room_id=room_id,
        target_setpoint_c=21,
        base_reason=CommandReason.VACANT_SETPOINT,
        eval_id=uuid.uuid4(),
    )

    status = next(z for z in pro_zone if z["zone_id"] == zone_id)
    # ``detail`` steht nur im leeren Zweig — im normalen Pfad fehlt der
    # Schluessel ganz, und das ist die Aussage: es gab etwas zu senden.
    assert status.get("detail") is None
    assert status["count_sent"] == 1, "das Ventil bekommt seinen Sollwert"
    assert [eui for eui, _ in gesendet] == [ventil.dev_eui]


async def test_nur_relais_erkennt_die_leere_zone_nicht_als_relais_zone(
    db_session: AsyncSession,
) -> None:
    """``all()`` auf einer leeren Liste ist ``True`` — die Falle dieser Funktion.

    Ohne die ``bool(alle)``-Bedingung waere jede leere Zone eine
    Relais-Zone, und der Grund im Trace waere schlicht falsch.
    """
    _, zone_id = await _zimmer(db_session, marker="nix")
    assert await _zone_hat_nur_relais(db_session, zone_id) is False
