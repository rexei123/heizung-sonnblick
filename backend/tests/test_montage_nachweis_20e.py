"""Sprint 20e — der Montage-Nachweis: wann er entsteht und wann er wieder weggeht.

**Worum es geht.** Layer 4 der Engine fragte bisher "sitzt das Geraet
**jetzt**?" und las dafuer ``attached_backplate`` des letzten Frames. Der
Taster meldet im Haus zu oft ein falsches Nein, die Engine schaltete daraufhin
in den Frostschutz, und am Ende hat dem Melder niemand mehr geglaubt (§5.79).

20e dreht die Frage um: "**war** es je belegt montiert?" — eine
Lebenszyklus-Tatsache (``device.mounted_confirmed_at``, Migration 0027) statt
eines Zustands.

Drei Dinge werden hier geprueft, und sie haben verschiedene Fehlerbilder:

1. **Die Bedingung** (T3, ohne Datenbank): beide Merkmale im **selben** Frame.
   Faellt sie zu weit aus, bekommt ein Geraet auf dem Werkstatt-Tisch einen
   Nachweis — und ist danach dauerhaft von der Detached-Pruefung
   ausgenommen, ohne je montiert gewesen zu sein.
2. **Die Schreibbedingungen** (T3, mit Datenbank): genau ein Schreibvorgang
   je Geraet und Lebenszeit, nur mit Zuordnung, nur fuer aktive Geraete.
3. **Die Loeschung** (T12): Detach, Retire und Replace nehmen den Nachweis
   mit. Bleibt er stehen, kommt ein Pool-Rueckläufer mit einem Nachweis
   zurueck, den niemand erbracht hat.

Teil 1 laeuft ohne Datenbank und damit auch lokal (B-18-5). Teil 2 und 3
skippen ohne ``TEST_DATABASE_URL`` (§5.50).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.scripts.backfill_mounted_confirmed import ermittle, schreibe
from heizung.services.mqtt_subscriber import _maybe_confirm_mounted

pytestmark = pytest.mark.asyncio

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt — DB-Tests brauchen Postgres"

# 8 Hex-Prefix + 8 Zeichen Suffix = 16 = VARCHAR(16) exakt voll (§5.18).
EUI_PREFIX = "20e0a027"

SEEN_AT = datetime(2026, 10, 7, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Teil 1 — die Bedingung, ohne Datenbank
# ---------------------------------------------------------------------------


class _Mitschrift:
    """Zaehlt, ob der Nachweis-Pfad ueberhaupt ein ``UPDATE`` abgesetzt hat.

    Gezaehlt wird am **Eingang**, nicht am Ergebnis. Ein Test, der nur auf
    "Spalte ist NULL geblieben" prueft, waere auch gruen, wenn das
    ``UPDATE`` laeuft und erst die ``WHERE``-Klausel es verwirft — und damit
    haette er die eigentliche Bedingung nie geprueft. Hier soll die Funktion
    gar nicht erst zur Datenbank gehen.

    Bei 104 Geraeten und einem Keep-alive alle zehn Minuten sind das rund
    15 000 Frames am Tag; ein ``UPDATE`` je Frame waere nicht falsch, aber
    verschwendet.
    """

    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object, *_args: object, **_kwargs: object) -> None:
        self.statements.append(statement)
        return


def _werte(**overrides: Any) -> dict[str, Any]:
    """Ein ``_map_to_reading``-Ergebnis mit beiden Merkmalen, ueberschreibbar."""
    werte: dict[str, Any] = {
        "attached_backplate": True,
        "valve_position": 80,
        "temperature": Decimal("21.0"),
    }
    werte.update(overrides)
    return werte


async def test_beide_merkmale_im_selben_frame_setzen_den_nachweis() -> None:
    """Die Gegenprobe zu allen folgenden Tests: der Positivfall kommt durch.

    Ohne diesen Test waere ein ``return`` am Funktionsanfang gruen — die
    Bedingung soll **einen** Fall durchlassen, nicht keinen.
    """
    m = _Mitschrift()

    await _maybe_confirm_mounted(m, 7, _werte(), SEEN_AT)  # type: ignore[arg-type]

    assert len(m.statements) == 1


@pytest.mark.parametrize(
    ("feld", "wert", "warum"),
    [
        ("attached_backplate", False, "Taster meldet ausdruecklich 'nicht aufgesetzt'"),
        ("attached_backplate", None, "alter Codec ohne das Feld — kein Wert ist kein Beleg"),
        ("valve_position", 0, "Ventil geschlossen: kein Beleg, dass ein Ventil da ist"),
        ("valve_position", None, "Reply-Frame ohne Ventilwert"),
    ],
)
async def test_ein_fehlendes_merkmal_genuegt_nicht(feld: str, wert: Any, warum: str) -> None:
    """Beide Merkmale, oder keiner. Die Bedingung ist ein UND.

    Der Fall ``attached_backplate=None`` ist der wichtigste: ``None`` heisst
    "dieses Feld steht nicht im Frame" und ist etwas anderes als ``False``
    (dieselbe Drei-Zustands-Regel wie in Migration 0025). Ein Vergleich
    ``if not werte.get(...)`` haette beide gleich behandelt — richtig, aber
    aus Versehen; die Pruefung ist deshalb auf ``is not True`` formuliert.
    """
    m = _Mitschrift()

    await _maybe_confirm_mounted(m, 7, _werte(**{feld: wert}), SEEN_AT)  # type: ignore[arg-type]

    assert m.statements == [], warum


async def test_ventil_offen_aber_taster_nicht_zaehlt_nicht() -> None:
    """**Warum die Gleichzeitigkeit zaehlt und nicht die Historie.**

    Jedes Merkmal allein ist erklaerbar, ohne dass das Geraet montiert ist:
    den Taster kann eine Hand druecken, und der Motor fahrt auch in der Luft.
    Erst zusammen schliessen sie beides aus — der Taster sagt "etwas drueckt
    von hinten", das Ventil sagt "und zwar ein Ventil".

    Der Backfill (T2) urteilt bewusst anders, weil er die Merkmale in
    getrennten Frames gelten laesst. Der Grund steht dort im Docstring und
    ist ein Schema-Zeitproblem, keine Lockerung der Fachregel.
    """
    m = _Mitschrift()

    await _maybe_confirm_mounted(
        m,  # type: ignore[arg-type]
        7,
        _werte(attached_backplate=None, valve_position=100),
        SEEN_AT,
    )

    assert m.statements == []


# ---------------------------------------------------------------------------
# Teil 2 + 3 — mit Datenbank
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        try:
            await _purge(session)
            await session.commit()
            yield session
        finally:
            await session.rollback()
            await _purge(session)
            await session.commit()
    await engine.dispose()


async def _purge(session: AsyncSession) -> None:
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.dev_eui.like(f"{EUI_PREFIX}%"))))
        .scalars()
        .all()
    )
    if device_ids:
        await session.execute(
            sa_delete(SensorReading).where(SensorReading.device_id.in_(device_ids))
        )
        # ``replaced_by_device_id`` zeigt von einem Test-Geraet auf ein
        # anderes; die FK ist ``ON DELETE SET NULL``, aber die Reihenfolge
        # innerhalb eines Statements ist nicht garantiert. Erst loesen.
        await session.execute(
            sa_delete(Device).where(Device.id.in_(device_ids)).where(Device.retired_at.is_not(None))
        )
        await session.execute(sa_delete(Device).where(Device.id.in_(device_ids)))
    await session.execute(sa_delete(Room).where(Room.number.like("20e-%")))
    await session.execute(sa_delete(RoomType).where(RoomType.name.like("20e-%")))


async def _make_zone(session: AsyncSession) -> int:
    """Zimmer + Zone, damit ein Geraet zugeordnet sein kann.

    # schema_constraint: room.number max 20 chars, room_type.name max 50
    # schema_constraint: heating_zone.kind NOT NULL (HeatingZoneKind)

    ``20e-`` + 8 Hex = 12 Zeichen (§5.18, §5.49). ``kind`` hat weder
    Python- noch Server-Default — der erste CI-Lauf dieses PRs ist genau
    daran gescheitert.
    """
    suffix = uuid.uuid4().hex[:8]
    rt = RoomType(name=f"20e-{suffix}")
    session.add(rt)
    await session.flush()
    room = Room(number=f"20e-{suffix}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    zone = HeatingZone(room_id=room.id, name="Schlafzimmer", kind=HeatingZoneKind.BEDROOM)
    session.add(zone)
    await session.flush()
    return zone.id


async def _make_device(session: AsyncSession, *, zone_id: int | None = None) -> Device:
    # Hinweis fuer Aufrufer: ``device.id`` NICHT nach ``expire_all()`` lesen.
    # SQLAlchemy versucht dann einen sync-gebrueckten Refresh, der unter
    # asyncpg mit ``MissingGreenlet`` bricht (§5.38). Die ID vorher in eine
    # lokale Variable holen.
    device = Device(
        dev_eui=f"{EUI_PREFIX}{uuid.uuid4().hex[:8]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        heating_zone_id=zone_id,
    )
    session.add(device)
    await session.flush()
    return device


async def test_nachweis_wird_mit_zuordnung_gesetzt(db_session: AsyncSession) -> None:
    """Der Positivfall in der Datenbank: Zeitstempel ist der Frame-Zeitpunkt."""
    zone_id = await _make_zone(db_session)
    device_id = (await _make_device(db_session, zone_id=zone_id)).id

    await _maybe_confirm_mounted(db_session, device_id, _werte(), SEEN_AT)
    await db_session.flush()
    db_session.expire_all()

    frisch = await db_session.get(Device, device_id)
    assert frisch is not None
    assert frisch.mounted_confirmed_at == SEEN_AT


async def test_zweiter_frame_ueberschreibt_den_nachweis_nicht(db_session: AsyncSession) -> None:
    """Ein Schreibvorgang je Geraet und Lebenszeit.

    Ohne ``WHERE mounted_confirmed_at IS NULL`` waere der Nachweis kein
    Nachweis, sondern ein "zuletzt gesehen" — und damit dasselbe
    Zustandsfeld, das 20e gerade abschafft.
    """
    zone_id = await _make_zone(db_session)
    device_id = (await _make_device(db_session, zone_id=zone_id)).id

    await _maybe_confirm_mounted(db_session, device_id, _werte(), SEEN_AT)
    await _maybe_confirm_mounted(db_session, device_id, _werte(), SEEN_AT + timedelta(days=3))
    await db_session.flush()
    db_session.expire_all()

    frisch = await db_session.get(Device, device_id)
    assert frisch is not None
    assert frisch.mounted_confirmed_at == SEEN_AT, "der erste Beleg gilt"


async def test_pool_geraet_ohne_zone_bekommt_keinen_nachweis(db_session: AsyncSession) -> None:
    """**Der Fall, der den Eingangstest betrifft.**

    Der Eingangstest fahrt jedes Geraet auf 28 °C und erwartet dort eine
    Ventiloeffnung — ein Pool-Vicki auf dem Tisch erfuellt dabei beide
    Merkmale in einem Frame, wenn der Taster gedrueckt ist. "Montiert" ist
    aber eine Aussage ueber einen Heizkoerper, nicht ueber ein Geraet.
    """
    device_id = (await _make_device(db_session, zone_id=None)).id

    await _maybe_confirm_mounted(db_session, device_id, _werte(), SEEN_AT)
    await db_session.flush()
    db_session.expire_all()

    frisch = await db_session.get(Device, device_id)
    assert frisch is not None
    assert frisch.mounted_confirmed_at is None


async def test_ausgemustertes_geraet_bekommt_keinen_nachweis(db_session: AsyncSession) -> None:
    """Ein abgenommenes, aber noch nicht entpaartes Geraet sendet weiter.

    Es liegt dann irgendwo und meldet Frames; einen frischen Nachweis soll
    es daraus nicht ziehen.
    """
    zone_id = await _make_zone(db_session)
    device = await _make_device(db_session, zone_id=zone_id)
    device.retired_at = SEEN_AT - timedelta(days=1)
    device.retired_reason = "defekt"
    await db_session.flush()
    device_id = device.id

    await _maybe_confirm_mounted(db_session, device_id, _werte(), SEEN_AT)
    await db_session.flush()
    db_session.expire_all()

    frisch = await db_session.get(Device, device_id)
    assert frisch is not None
    assert frisch.mounted_confirmed_at is None


# ---------------------------------------------------------------------------
# T12 — die Loeschung
# ---------------------------------------------------------------------------


async def test_retire_loescht_den_nachweis(db_session: AsyncSession) -> None:
    """Ein ausgemustertes Geraet traegt keinen Montage-Nachweis.

    Wichtig wegen AE-57: eine DevEUI darf nach einem Werksreset wieder
    verwendet werden. Ein stehengebliebener Nachweis waere dann eine Aussage
    ueber das Vorleben.
    """
    from heizung.services.device_service import retire_device

    zone_id = await _make_zone(db_session)
    device = await _make_device(db_session, zone_id=zone_id)
    device.mounted_confirmed_at = SEEN_AT
    await db_session.flush()
    device_id = device.id

    await retire_device(db_session, device_id=device_id, reason="defekt", user_id=None)
    await db_session.flush()
    db_session.expire_all()

    frisch = await db_session.get(Device, device_id)
    assert frisch is not None
    assert frisch.mounted_confirmed_at is None


async def test_replace_loescht_nur_beim_alten_geraet(db_session: AsyncSession) -> None:
    """Der alte Row verliert den Nachweis, der neue bekommt keinen.

    Das ist die Probe auf den Zweck: der Pool-Vicki ist nach dem Tausch
    **zugeordnet**, aber noch nicht montiert. Seinen Nachweis erbringt der
    erste Frame nach dem Einbau — genau dafuer gibt es die Spalte.
    """
    from heizung.services.device_service import replace_device

    zone_id = await _make_zone(db_session)
    alt = await _make_device(db_session, zone_id=zone_id)
    alt.mounted_confirmed_at = SEEN_AT
    neu = await _make_device(db_session, zone_id=None)
    await db_session.commit()

    alt_id, neu_id = alt.id, neu.id
    await replace_device(db_session, old_device_id=alt_id, new_pool_device_id=neu_id, user_id=None)
    await db_session.commit()
    db_session.expire_all()

    alt_frisch = await db_session.get(Device, alt_id)
    neu_frisch = await db_session.get(Device, neu_id)
    assert alt_frisch is not None and neu_frisch is not None
    assert alt_frisch.mounted_confirmed_at is None
    assert neu_frisch.heating_zone_id == zone_id, "der neue haengt jetzt an der Zone"
    assert neu_frisch.mounted_confirmed_at is None, "zugeordnet ist nicht montiert"


# ---------------------------------------------------------------------------
# T2 — der Backfill
# ---------------------------------------------------------------------------


async def _reading(
    session: AsyncSession,
    device_id: int,
    ts: datetime,
    *,
    fcnt: int,
    backplate: bool | None = None,
    valve: int | None = None,
) -> None:
    session.add(
        SensorReading(
            time=ts,
            device_id=device_id,
            fcnt=fcnt,
            attached_backplate=backplate,
            valve_position=valve,
        )
    )
    await session.flush()


async def test_backfill_nimmt_den_spaeteren_der_beiden_belege(db_session: AsyncSession) -> None:
    """**Das Kernurteil des Backfills.**

    Taster am 01.10., Ventil am 03.10. — ab dem 03.10. war beides gezeigt.
    Der fruehere Zeitpunkt waere zu optimistisch (da war erst die Haelfte
    belegt), der juengste Frame haette mit dem Nachweis nichts zu tun.
    """
    zone_id = await _make_zone(db_session)
    device_id = (await _make_device(db_session, zone_id=zone_id)).id
    taster_am = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    ventil_am = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)

    await _reading(db_session, device_id, taster_am, fcnt=1, backplate=True, valve=0)
    await _reading(db_session, device_id, ventil_am, fcnt=2, backplate=None, valve=65)
    await _reading(db_session, device_id, ventil_am + timedelta(days=1), fcnt=3, valve=0)

    befunde = await ermittle(db_session)
    meine = [b for b in befunde if b.device_id == device_id]
    assert len(meine) == 1
    assert meine[0].erster_taster == taster_am
    assert meine[0].erstes_ventil == ventil_am
    assert meine[0].nachweis_ab == ventil_am

    assert await schreibe(db_session, meine) == 1
    await db_session.flush()
    db_session.expire_all()
    frisch = await db_session.get(Device, device_id)
    assert frisch is not None
    assert frisch.mounted_confirmed_at == ventil_am


async def test_backfill_ueberspringt_geraet_mit_nur_einem_beleg(
    db_session: AsyncSession,
) -> None:
    """Ein Merkmal allein genuegt auch dem Backfill nicht.

    Das Geraet hat den Taster nie gemeldet (alter Codec oder nie
    aufgesetzt) — ein Nachweis waere hier eine Behauptung.
    """
    zone_id = await _make_zone(db_session)
    device_id = (await _make_device(db_session, zone_id=zone_id)).id
    await _reading(
        db_session,
        device_id,
        datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
        fcnt=1,
        backplate=None,
        valve=70,
    )

    befunde = await ermittle(db_session)
    assert [b for b in befunde if b.device_id == device_id] == []


async def test_backfill_ueberspringt_pool_und_bereits_bestaetigte(
    db_session: AsyncSession,
) -> None:
    """Zwei Ausschluesse in einem Test, weil sie dieselbe ``WHERE`` tragen.

    Der zweite macht den Lauf wiederholbar: ein Nachweis, den der
    Subscriber schon gesetzt hat, ist der genauere (beide Merkmale in einem
    Frame) und wird nicht ueberschrieben.
    """
    zone_id = await _make_zone(db_session)
    pool = await _make_device(db_session, zone_id=None)
    bestaetigt = await _make_device(db_session, zone_id=zone_id)
    bestaetigt.mounted_confirmed_at = SEEN_AT
    await db_session.flush()

    pool_id, bestaetigt_id = pool.id, bestaetigt.id
    for device_id in (pool_id, bestaetigt_id):
        await _reading(
            db_session,
            device_id,
            datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
            fcnt=1,
            backplate=True,
            valve=70,
        )

    befunde = await ermittle(db_session)
    gefunden = {b.device_id for b in befunde}
    assert pool_id not in gefunden
    assert bestaetigt_id not in gefunden


# ---------------------------------------------------------------------------
# T8-Abgleich: der Eingangstest stuetzt sich NICHT auf den Nachweis
# ---------------------------------------------------------------------------


async def test_eingangstest_liest_den_rohwert_und_nicht_den_nachweis() -> None:
    """**Der Lauf ist die Pruefung, die den Nachweis erzeugt.**

    Deshalb darf er sich nicht auf ihn stuetzen — sonst beurteilt er ein
    Geraet anhand eines Belegs, den er selbst erst erbringen soll. Beim
    zweiten Lauf (``--resume``) waere das Urteil dann zirkulaer: "montiert,
    weil beim letzten Mal montiert".

    Dieselbe Klasse wie die Zirkularitaet, die Sprint 20f-b beseitigt hat
    (die Engine adoptierte ihre eigene Bestaetigung als Gastwunsch).

    Der Test prueft die **Struktur** und nicht das Verhalten, weil es hier
    um eine Abwesenheit geht: ein Verhaltens-Test koennte nur zeigen, dass
    der Lauf heute das Richtige tut. Diese Zusicherung soll aber auch gelten,
    wenn jemand den Vor-Check umbaut und dabei nach einer bequemen
    Abkuerzung sucht — und `mounted_confirmed_at` ist genau so eine.

    Strukturtests dieser Art sind sonst selten im Repo; hier ist er
    gerechtfertigt, weil der Brief die Unberuehrtheit des Eingangstests
    ausdruecklich als T8-Punkt fuehrt und sie nicht aus einem Datenpfad
    folgt, sondern daraus, dass eine Abfrage **nicht** existiert.
    """
    from pathlib import Path

    quelle = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "heizung"
        / "scripts"
        / "pairing"
        / "batch_inbound_test.py"
    )
    text = quelle.read_text(encoding="utf-8")
    assert "mounted_confirmed" not in text, (
        "Der Eingangstest darf den Montage-Nachweis nicht lesen — er erzeugt ihn. "
        "Siehe AE-74 und Brief §7."
    )
    # Gegenprobe: er liest den Rohwert sehr wohl. Ohne diese Zeile waere der
    # Test auch gruen, wenn die Datei leer oder umbenannt waere.
    assert "attached_backplate" in text
