"""Sprint 15e (AE-66) — DB-Tests fuer reconcile_from_import + Watchdog + Log.

Skip ohne ``DATABASE_URL`` (CI-/Lokal-Pattern, vgl. test_override_pms_hook).
``reconcile_from_import`` committed selbst -> Cleanup pro Test via
``_isolate`` (wipe Import-Audits + purge ``t15e``-Prefix).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import OccupancySource, RoomStatus
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.schemas.occupancy_import import (
    OccupancyImportEntry,
    OccupancyImportPayload,
)
from heizung.services.occupancy_import_service import (
    ACTION_APPLIED,
    ACTION_CONFLICT,
    ACTION_REJECTED,
    ACTION_STALE,
    OccupancyImportRejectedError,
    get_import_log,
    reconcile_from_import,
    run_freshness_check,
)
from tests.conftest import purge_test_data_by_prefix

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"
PREFIX = "t15e"
VIENNA = ZoneInfo("Europe/Vienna")


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
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        try:
            yield s
        finally:
            await s.rollback()


async def _wipe(session: AsyncSession) -> None:
    await session.execute(text("DELETE FROM business_audit WHERE action LIKE 'OCCUPANCY_IMPORT%'"))
    await session.commit()
    await purge_test_data_by_prefix(session, PREFIX)


@pytest_asyncio.fixture(autouse=True)
async def _isolate(session: AsyncSession) -> AsyncIterator[None]:
    await _wipe(session)
    yield
    await _wipe(session)


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


async def _seed_room(session: AsyncSession, number: str) -> int:
    rt = RoomType(name=f"{PREFIX}-{uuid.uuid4().hex[:8]}")
    session.add(rt)
    await session.flush()
    room = Room(number=number, room_type_id=rt.id, status=RoomStatus.VACANT)
    session.add(room)
    await session.flush()
    return room.id


def _room_number(suffix: str) -> str:
    return f"{PREFIX}-{uuid.uuid4().hex[:6]}-{suffix}"


def _payload(
    *,
    received_at: str = "2026-06-06 07:14:15",
    entries: list[OccupancyImportEntry],
    ext_id: str | None = None,
) -> OccupancyImportPayload:
    return OccupancyImportPayload(
        id=ext_id or uuid.uuid4().hex,
        received_at=received_at,  # type: ignore[arg-type]  # validator parst den String
        liste=entries,
    )


def _entry(zimmer: str, anreise: str, abreise: str, typ: str | None = None) -> OccupancyImportEntry:
    return OccupancyImportEntry(
        zimmer=zimmer,
        anreise=anreise,  # type: ignore[arg-type]
        abreise=abreise,  # type: ignore[arg-type]
        aufenthaltstyp=typ,
    )


async def _active_pms(session: AsyncSession, room_id: int) -> list[Occupancy]:
    stmt = select(Occupancy).where(
        and_(
            Occupancy.room_id == room_id,
            Occupancy.is_active.is_(True),
            Occupancy.source == OccupancySource.PMS,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _audits(session: AsyncSession, action: str) -> list[BusinessAudit]:
    return list(
        (await session.execute(select(BusinessAudit).where(BusinessAudit.action == action)))
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Reconcile-Tests
# ---------------------------------------------------------------------------


async def test_anreise_creates_pms_occupancy(session: AsyncSession) -> None:
    num = _room_number("101")
    room_id = await _seed_room(session, num)

    outcome = await reconcile_from_import(
        session,
        payload=_payload(entries=[_entry(num, "04.06.2026", "06.06.2026", "Abreise")]),
    )

    assert outcome.status == "applied"
    assert outcome.rooms_occupied == 1
    occs = await _active_pms(session, room_id)
    assert len(occs) == 1
    assert occs[0].external_id == outcome.external_id


async def test_abreise_checkout_time_correct(session: AsyncSession) -> None:
    num = _room_number("102")
    room_id = await _seed_room(session, num)
    await reconcile_from_import(
        session, payload=_payload(entries=[_entry(num, "04.06.2026", "06.06.2026")])
    )
    occ = (await _active_pms(session, room_id))[0]
    expected_out = datetime(2026, 6, 6, 11, 0, tzinfo=VIENNA).astimezone(UTC)
    expected_in = datetime(2026, 6, 4, 14, 0, tzinfo=VIENNA).astimezone(UTC)
    assert occ.check_out == expected_out
    assert occ.check_in == expected_in


async def test_zimmerwechsel_only_target_room(session: AsyncSession) -> None:
    target = _room_number("101")
    room_id = await _seed_room(session, target)
    # "52" existiert NICHT als Zimmer; nur das Zielzimmer nach ⇒ zaehlt.
    outcome = await reconcile_from_import(
        session,
        payload=_payload(
            entries=[_entry(f"52\n⇒ {target}", "05.06.2026", "07.06.2026", "Zimmerwechsel")]
        ),
    )
    assert outcome.status == "applied"
    assert len(await _active_pms(session, room_id)) == 1


async def test_previously_pms_now_missing_is_closed(session: AsyncSession) -> None:
    gone = _room_number("201")
    kept = _room_number("202")
    gone_id = await _seed_room(session, gone)
    kept_id = await _seed_room(session, kept)
    # Bestehende aktive pms-Belegung fuer "gone", die list_date 06.06 ueberlappt.
    session.add(
        Occupancy(
            room_id=gone_id,
            check_in=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
            check_out=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
            source=OccupancySource.PMS,
            external_id="prev",
        )
    )
    await session.flush()

    outcome = await reconcile_from_import(
        session, payload=_payload(entries=[_entry(kept, "06.06.2026", "08.06.2026")])
    )

    assert outcome.rooms_closed == 1
    assert await _active_pms(session, gone_id) == []
    assert len(await _active_pms(session, kept_id)) == 1


async def test_unknown_number_rejects_atomic(session: AsyncSession) -> None:
    valid = _room_number("101")
    valid_id = await _seed_room(session, valid)

    with pytest.raises(OccupancyImportRejectedError):
        await reconcile_from_import(
            session,
            payload=_payload(
                entries=[
                    _entry(valid, "04.06.2026", "06.06.2026"),
                    _entry("t15e-does-not-exist-999", "04.06.2026", "06.06.2026"),
                ]
            ),
        )

    # Atomar: KEINE Belegung geschrieben, aber ein REJECTED-Audit.
    assert await _active_pms(session, valid_id) == []
    assert len(await _audits(session, ACTION_REJECTED)) == 1


async def test_manual_conflict_skips_pms_processes_rest(session: AsyncSession) -> None:
    conflicted = _room_number("301")
    other = _room_number("302")
    conflicted_id = await _seed_room(session, conflicted)
    other_id = await _seed_room(session, other)
    manual = Occupancy(
        room_id=conflicted_id,
        check_in=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
        check_out=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        source=OccupancySource.MANUAL,
    )
    session.add(manual)
    await session.flush()
    manual_id = manual.id

    outcome = await reconcile_from_import(
        session,
        payload=_payload(
            entries=[
                _entry(conflicted, "04.06.2026", "06.06.2026"),
                _entry(other, "04.06.2026", "06.06.2026"),
            ]
        ),
    )

    assert outcome.conflicts == 1
    assert outcome.rooms_occupied == 1  # nur "other"
    # Kein pms fuer das Konflikt-Zimmer, manual unberuehrt.
    assert await _active_pms(session, conflicted_id) == []
    manual_after = await session.get(Occupancy, manual_id)
    assert manual_after is not None and manual_after.is_active is True
    # "other" wurde regulaer angelegt.
    assert len(await _active_pms(session, other_id)) == 1
    assert len(await _audits(session, ACTION_CONFLICT)) == 1


async def test_idempotent_same_id_and_list_date(session: AsyncSession) -> None:
    num = _room_number("401")
    room_id = await _seed_room(session, num)
    ext_id = uuid.uuid4().hex
    pl = _payload(entries=[_entry(num, "04.06.2026", "06.06.2026")], ext_id=ext_id)

    first = await reconcile_from_import(session, payload=pl)
    assert first.status == "applied"
    second = await reconcile_from_import(
        session,
        payload=_payload(entries=[_entry(num, "04.06.2026", "06.06.2026")], ext_id=ext_id),
    )
    assert second.status == "already_processed"
    # Keine Dublette.
    assert len(await _active_pms(session, room_id)) == 1
    assert len(await _audits(session, ACTION_APPLIED)) == 1


async def test_empty_list_closes_all_pms(session: AsyncSession) -> None:
    num = _room_number("501")
    room_id = await _seed_room(session, num)
    session.add(
        Occupancy(
            room_id=room_id,
            check_in=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
            check_out=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
            source=OccupancySource.PMS,
        )
    )
    await session.flush()

    outcome = await reconcile_from_import(session, payload=_payload(entries=[]))

    assert outcome.status == "applied"
    assert outcome.rooms_closed == 1
    assert await _active_pms(session, room_id) == []


# ---------------------------------------------------------------------------
# Watchdog-Tests
# ---------------------------------------------------------------------------


async def test_watchdog_stale_writes_audit_and_frees_no_rooms(session: AsyncSession) -> None:
    num = _room_number("601")
    room_id = await _seed_room(session, num)
    occ = Occupancy(
        room_id=room_id,
        check_in=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
        check_out=datetime(2026, 6, 7, 12, 0, tzinfo=UTC),
        source=OccupancySource.PMS,
    )
    session.add(occ)
    await session.commit()

    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)  # lokal 10:00, nach 09:00
    result = await run_freshness_check(session, expected_by_local_str="09:00", now=now)

    assert result["stale"] is True
    stale = await _audits(session, ACTION_STALE)
    assert len(stale) == 1
    nv = stale[0].new_value
    assert isinstance(nv, dict) and nv["list_date"] == "2026-06-06"
    # Keine Zimmer freigegeben — letzter Stand eingefroren.
    refreshed = await session.get(Occupancy, occ.id)
    assert refreshed is not None and refreshed.is_active is True


async def test_watchdog_not_stale_when_import_present(session: AsyncSession) -> None:
    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    session.add(
        BusinessAudit(
            action=ACTION_APPLIED,
            target_type="occupancy_import",
            target_id=None,
            old_value=None,
            new_value={
                "external_id": "x",
                "list_date": "2026-06-06",
                "received_at": "2026-06-06T05:14:15+00:00",
                "rooms_occupied": 3,
                "rooms_closed": 0,
                "conflicts": 0,
                "result": "applied",
            },
            ts=now,
        )
    )
    await session.commit()

    result = await run_freshness_check(session, expected_by_local_str="09:00", now=now)
    assert result["stale"] is False
    assert await _audits(session, ACTION_STALE) == []


async def test_watchdog_before_expected_is_noop(session: AsyncSession) -> None:
    now = datetime(2026, 6, 6, 5, 0, tzinfo=UTC)  # lokal 07:00, vor 09:00
    result = await run_freshness_check(session, expected_by_local_str="09:00", now=now)
    assert result == {"stale": False, "reason": "before_expected"}
    assert await _audits(session, ACTION_STALE) == []


# ---------------------------------------------------------------------------
# Lese-Endpoint (get_import_log)
# ---------------------------------------------------------------------------


async def test_get_import_log_shape_and_status(session: AsyncSession) -> None:
    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    session.add_all(
        [
            BusinessAudit(
                action=ACTION_REJECTED,
                target_type="occupancy_import",
                target_id=None,
                old_value=None,
                new_value={
                    "external_id": "rej-1",
                    "list_date": "2026-06-05",
                    "received_at": "2026-06-05T05:14:15+00:00",
                    "rooms_occupied": 0,
                    "rooms_closed": 0,
                    "conflicts": 0,
                    "result": "rejected",
                },
                ts=datetime(2026, 6, 6, 7, 0, tzinfo=UTC),
            ),
            BusinessAudit(
                action=ACTION_APPLIED,
                target_type="occupancy_import",
                target_id=None,
                old_value=None,
                new_value={
                    "external_id": "app-1",
                    "list_date": "2026-06-06",
                    "received_at": "2026-06-06T05:14:15+00:00",
                    "rooms_occupied": 4,
                    "rooms_closed": 1,
                    "conflicts": 0,
                    "result": "applied",
                },
                ts=now,
            ),
        ]
    )
    await session.commit()

    resp = await get_import_log(session, expected_by_local_str="09:00", now=now)

    assert resp.status == "green"  # today_received
    assert resp.today_received is True
    assert resp.expected_by_local == "09:00"
    assert resp.last_success_at == datetime(2026, 6, 6, 5, 14, 15, tzinfo=UTC)
    assert len(resp.imports) == 2
    # neueste zuerst
    assert resp.imports[0].external_id == "app-1"
    assert resp.imports[0].result == "applied"
    assert resp.imports[0].rooms_occupied == 4
    assert resp.imports[1].result == "rejected"
