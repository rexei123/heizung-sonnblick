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
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
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
from heizung.models.global_config import GlobalConfig
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
# Sprint 15e-1 — reales Datumsformat (Anreise ohne Jahr)
# ---------------------------------------------------------------------------


async def test_real_payload_anreise_without_year(session: AsyncSession) -> None:
    """Reales 07.06-Format: Anreise ohne Jahr + Zimmerwechsel -> kein 422."""
    a = _room_number("101")
    b = _room_number("201")
    a_id = await _seed_room(session, a)
    b_id = await _seed_room(session, b)

    outcome = await reconcile_from_import(
        session,
        payload=_payload(
            entries=[
                _entry(a, "04.06.", "06.06.2026", "Abreise"),
                _entry(f"52\n⇒ {b}", "05.06.", "07.06.2026", "Zimmerwechsel"),
            ]
        ),
    )

    assert outcome.status == "applied"
    assert outcome.rooms_occupied == 2
    occ_a = (await _active_pms(session, a_id))[0]
    assert occ_a.check_in == datetime(2026, 6, 4, 14, 0, tzinfo=VIENNA).astimezone(UTC)
    assert occ_a.check_out == datetime(2026, 6, 6, 11, 0, tzinfo=VIENNA).astimezone(UTC)
    assert len(await _active_pms(session, b_id)) == 1


async def test_silvester_year_wrap_e2e(session: AsyncSession) -> None:
    """Anreise 29.12. (ohne Jahr) + Abreise 02.01.2027 -> check_in 29.12.2026."""
    num = _room_number("301")
    room_id = await _seed_room(session, num)

    outcome = await reconcile_from_import(
        session,
        payload=_payload(
            received_at="2027-01-02 07:14:15",
            entries=[_entry(num, "29.12.", "02.01.2027", "Abreise")],
        ),
    )

    assert outcome.status == "applied"
    occ = (await _active_pms(session, room_id))[0]
    assert occ.check_in == datetime(2026, 12, 29, 14, 0, tzinfo=VIENNA).astimezone(UTC)
    assert occ.check_out == datetime(2027, 1, 2, 11, 0, tzinfo=VIENNA).astimezone(UTC)


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
    result = await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

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
                "received_at": "2026-06-06T07:14:15+00:00",
                "rooms_occupied": 3,
                "rooms_closed": 0,
                "conflicts": 0,
                "result": "applied",
            },
            ts=now,
        )
    )
    await session.commit()

    result = await run_freshness_check(session, expected_by_local=time(9, 0), now=now)
    assert result["stale"] is False
    assert await _audits(session, ACTION_STALE) == []


async def test_watchdog_before_expected_is_noop(session: AsyncSession) -> None:
    now = datetime(2026, 6, 6, 5, 0, tzinfo=UTC)  # lokal 07:00, vor 09:00
    result = await run_freshness_check(session, expected_by_local=time(9, 0), now=now)
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
                    "received_at": "2026-06-05T07:14:15+00:00",
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
                    "received_at": "2026-06-06T07:14:15+00:00",
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

    resp = await get_import_log(session, expected_by_local=time(9, 0), now=now)

    assert resp.status == "green"  # today_received
    assert resp.today_received is True
    assert resp.expected_by_local == "09:00"
    assert resp.last_success_at == datetime(2026, 6, 6, 7, 14, 15, tzinfo=UTC)
    assert len(resp.imports) == 2
    # neueste zuerst
    assert resp.imports[0].external_id == "app-1"
    assert resp.imports[0].result == "applied"
    assert resp.imports[0].rooms_occupied == 4
    assert resp.imports[1].result == "rejected"


# ---------------------------------------------------------------------------
# Sprint 18 / T3 — Alarm-Mail zum Watchdog
# ---------------------------------------------------------------------------
#
# Bis Sprint 17 stand an dieser Stelle der Kommentar "Email-Alarm
# absichtlich NICHT implementiert". Der Watchdog schrieb ein Audit, das
# ausser seinem eigenen Idempotenz-Guard niemand las. Seit Sprint 18 geht
# eine Mail raus — gebremst, damit ein langes Wochenende nicht jeden Tag
# dieselbe Nachricht erzeugt.


class _Postfach:
    def __init__(self) -> None:
        self.mails: list[dict[str, str]] = []

    def __call__(self, *, recipient: str | None, subject: str, body: str) -> Any:
        from heizung.services.mailer import MailResult

        self.mails.append({"recipient": recipient or "", "subject": subject, "body": body})
        return MailResult(True, None, "Testzustellung")


class _AlarmRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> Any:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


async def _set_alert_email(session: AsyncSession, adresse: str | None) -> None:
    gc = await session.get(GlobalConfig, 1)
    assert gc is not None, "global_config-Singleton fehlt"
    gc.alert_email = adresse
    await session.commit()


async def test_watchdog_verschickt_alarm_mail(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heizung.services import occupancy_import_service as svc
    from heizung.services import redis_client

    postfach = _Postfach()
    monkeypatch.setattr(svc.mailer, "send_mail", postfach)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _AlarmRedis())
    await _set_alert_email(session, "chef@example.com")

    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    result = await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

    assert result["stale"] is True
    assert len(postfach.mails) == 1
    mail = postfach.mails[0]
    assert "06.06.2026" in mail["subject"]
    # Der Text muss sagen, was das System TUT — nicht nur, was fehlt.
    assert "eingefroren" in mail["body"]
    assert "kein Zimmer freigegeben" in mail["body"]


async def test_watchdog_ohne_alarm_adresse_schreibt_nur_das_audit(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heizung.services import occupancy_import_service as svc
    from heizung.services import redis_client

    postfach = _Postfach()
    monkeypatch.setattr(svc.mailer, "send_mail", postfach)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _AlarmRedis())
    await _set_alert_email(session, None)

    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    result = await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

    assert result["stale"] is True
    assert len(await _audits(session, ACTION_STALE)) == 1
    assert postfach.mails == []


async def test_watchdog_alarm_wird_pro_tag_nur_einmal_verschickt(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Audit-Guard verhindert den zweiten Lauf am selben Tag ohnehin.
    Die Bremse ist die zweite Schicht — sie greift auch dann, wenn der
    Guard aus irgendeinem Grund nicht zieht."""
    from heizung.services import alert_throttle, redis_client
    from heizung.services import occupancy_import_service as svc

    postfach = _Postfach()
    geteilt = _AlarmRedis()
    monkeypatch.setattr(svc.mailer, "send_mail", postfach)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: geteilt)
    await _set_alert_email(session, "chef@example.com")

    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

    # Das Audit von Hand entfernen, damit der Guard NICHT greift — jetzt
    # ist die Bremse allein zustaendig.
    for a in await _audits(session, ACTION_STALE):
        await session.delete(a)
    await session.commit()

    await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

    assert len(postfach.mails) == 1, "die Bremse haelt, auch ohne Audit-Guard"
    assert alert_throttle.KIND_IMPORT_STALE in " ".join(geteilt.store)


async def test_watchdog_versandfehler_bricht_den_lauf_nicht_ab(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Das Audit ist die Spur, die Mail die Benachrichtigung. Bleibt die
    Mail stecken, muss das Audit trotzdem stehen."""
    from heizung.services import occupancy_import_service as svc
    from heizung.services import redis_client
    from heizung.services.mailer import MailResult

    def _scheitert(**kwargs: Any) -> MailResult:
        return MailResult(False, "SMTPConnectError", "Server nicht erreichbar")

    monkeypatch.setattr(svc.mailer, "send_mail", _scheitert)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _AlarmRedis())
    await _set_alert_email(session, "chef@example.com")

    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    result = await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

    assert result["stale"] is True
    assert len(await _audits(session, ACTION_STALE)) == 1


async def test_watchdog_haelt_den_versandversuch_fest(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4: auch der Import-Alarm schreibt seinen Versandstatus.

    Der zweite Alarmweg neben dem Health-Beat. Faellt hier die Verdrahtung
    weg, zeigt die Oberflaeche den Stand eines *anderen* Alarms — und wer
    nachsieht, warum keine Mail kam, liest den falschen Befund.
    """
    from heizung.models.global_config import GlobalConfig
    from heizung.services import occupancy_import_service as svc
    from heizung.services import redis_client
    from heizung.services.mailer import MailResult

    def _scheitert(**kwargs: Any) -> MailResult:
        return MailResult(False, "SMTPAuthenticationError", "535 5.7.8 nicht akzeptiert")

    monkeypatch.setattr(svc.mailer, "send_mail", _scheitert)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _AlarmRedis())
    await _set_alert_email(session, "chef@example.com")

    gc = await session.get(GlobalConfig, 1)
    assert gc is not None
    gc.last_mail_attempt_at = None
    gc.last_mail_error = None
    await session.commit()

    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    await run_freshness_check(session, expected_by_local=time(9, 0), now=now)

    await session.refresh(gc)
    assert gc.last_mail_attempt_at is not None
    assert gc.last_mail_error is not None
    assert gc.last_mail_error.startswith("SMTPAuthenticationError")


# ---------------------------------------------------------------------------
# Zeitzonen-Fix 26.09.2026 — Eingang, Schwelle, DST
#
# Anlass: Der Watchdog hat am 26.09. um 10:15 Ortszeit Alarm geschlagen. Die
# Liste kam um 10:38, also 23 Minuten spaeter, puenktlich wie an den 20 Tagen
# davor. Zwei Ursachen, die zusammen wirkten:
#
#   1. ``payload.received_at`` von mailparser ist UTC, wurde aber per
#      ``.replace(tzinfo=tz)`` zur Ortszeit **erklaert**. Der gespeicherte
#      Eingang lag damit zwei Stunden zu frueh (06:38 statt 08:38 UTC).
#      Beleg aus der Produktion: ``business_audit.ts`` = 08:38+00 (echter
#      Eingang) gegen ``new_value.received_at`` = 06:38+00 in derselben Zeile.
#   2. Die Oberflaeche zeigte diesen falschen Wert als "08:38", ohne Einheit,
#      direkt neben "Erwartet bis 09:00 Uhr". Daraus wurde die Schwelle 09:00
#      abgeleitet — sie haette hinter 10:38 liegen muessen.
#
# Der **Vergleich** war die ganze Zeit korrekt (Ortszeit gegen Ortszeit,
# AE-60). Deshalb pinnen diese Tests den Eingang und die Schwelle, nicht die
# Vergleichslogik.
# ---------------------------------------------------------------------------


async def test_eingang_wird_als_utc_gelesen(session: AsyncSession) -> None:
    """Der Kern des Fehlers vom 26.09.

    mailparser sendet ``"2026-09-26 08:38:27"`` — das ist UTC. Gespeichert
    werden muss genau dieser Augenblick, nicht der zwei Stunden fruehere.
    """
    num = _room_number("501")
    await _seed_room(session, num)
    payload = _payload(
        entries=[_entry(num, "26.09.", "28.09.2026")],
        received_at="2026-09-26 08:38:27",
        ext_id="tz-utc-1",
    )

    await reconcile_from_import(
        session, payload=payload, now=datetime(2026, 9, 26, 8, 40, tzinfo=UTC)
    )

    audits = await _audits(session, ACTION_APPLIED)
    nv = audits[0].new_value
    assert isinstance(nv, dict)
    # 08:38:27 UTC — NICHT 06:38:27. Vor dem Fix stand hier der fruehere Wert.
    assert nv["received_at"] == "2026-09-26T08:38:27+00:00"


async def test_list_date_kommt_aus_der_ortszeit(session: AsyncSession) -> None:
    """Der Kalendertag ist der des Hotels, nicht der von UTC.

    Ein Versand um 23:30 UTC liegt im Winter bereits am Folgetag Ortszeit.
    Wuerde ``list_date`` aus dem UTC-Datum kommen, gehoerte die Liste zum
    Vortag — und der Watchdog suchte am naechsten Morgen eine Liste, die
    unter dem falschen Tag abgelegt ist.
    """
    num = _room_number("502")
    await _seed_room(session, num)
    payload = _payload(
        entries=[_entry(num, "03.01.", "05.01.2027")],
        received_at="2027-01-02 23:30:00",  # UTC -> 03.01. 00:30 MEZ
        ext_id="tz-utc-2",
    )

    out = await reconcile_from_import(
        session, payload=payload, now=datetime(2027, 1, 2, 23, 35, tzinfo=UTC)
    )

    assert out.list_date == date(2027, 1, 3)


# --- Schwelle aus der Konfiguration ----------------------------------------


async def _set_expected_by(session: AsyncSession, value: time) -> None:
    gc = await session.get(GlobalConfig, 1)
    assert gc is not None
    gc.occupancy_import_expected_by_local = value
    await session.commit()


async def test_schwelle_kommt_aus_global_config(session: AsyncSession) -> None:
    """Ohne Parameter laedt der Watchdog die Schwelle selbst.

    Das ist der Produktionspfad. Vor dem Fix stand der Wert in der
    Umgebung — unsichtbar fuer den Hotelier und nur per SSH aenderbar.
    """
    await _set_expected_by(session, time(12, 0))

    # 11:00 Ortszeit (09:00 UTC im Sommer): noch vor 12:00 -> kein Alarm.
    frueh = await run_freshness_check(session, now=datetime(2026, 9, 26, 9, 0, tzinfo=UTC))
    assert frueh == {"stale": False, "reason": "before_expected"}

    # 13:00 Ortszeit: nach 12:00 -> Alarm.
    spaet = await run_freshness_check(session, now=datetime(2026, 9, 26, 11, 0, tzinfo=UTC))
    assert spaet["stale"] is True


async def test_der_alarm_vom_26_09_faellt_mit_12_uhr_weg(session: AsyncSession) -> None:
    """Die Regressionsprobe auf den konkreten Vorfall.

    Genau der Zeitpunkt, an dem der Watchdog damals Alarm geschlagen hat:
    08:15 UTC = 10:15 MESZ. Mit der Schwelle 12:00 ist das ein No-op, und die
    Liste hat bis 10:38 Zeit.
    """
    await _set_expected_by(session, time(12, 0))

    result = await run_freshness_check(session, now=datetime(2026, 9, 26, 8, 15, tzinfo=UTC))

    assert result == {"stale": False, "reason": "before_expected"}
    assert await _audits(session, ACTION_STALE) == []


# --- DST: der teure Teil ---------------------------------------------------
#
# Ab 25.10.2026 gilt MEZ. Versendet Casablanca weiter um 10:38 Ortszeit,
# wandert der UTC-Zeitstempel von 08:38 auf 09:38. Eine in UTC gerechnete
# Schwelle laege dann still eine Stunde daneben — sechs Tage vor dem Go-Live.
# Die drei Faelle analog AE-60: Sommer, Winter, Wechseltag.


async def test_dst_sommer_11_uhr_ortszeit_ist_vor_zwoelf(session: AsyncSession) -> None:
    await _set_expected_by(session, time(12, 0))
    # MESZ = UTC+2. 09:00 UTC -> 11:00 Ortszeit.
    result = await run_freshness_check(session, now=datetime(2026, 9, 26, 9, 0, tzinfo=UTC))
    assert result == {"stale": False, "reason": "before_expected"}


async def test_dst_winter_11_uhr_ortszeit_ist_vor_zwoelf(session: AsyncSession) -> None:
    """Derselbe Ortszeit-Moment, andere UTC-Uhrzeit.

    MEZ = UTC+1, also ist 11:00 Ortszeit hier 10:00 UTC. Ein in UTC
    gerechneter Vergleich gegen 12:00 haette im Sommer *und* im Winter
    dasselbe UTC-Fenster benutzt und damit einmal eine Stunde falsch
    gelegen. Genau diesen Fehler schliessen die beiden Tests zusammen aus.
    """
    await _set_expected_by(session, time(12, 0))
    result = await run_freshness_check(session, now=datetime(2026, 11, 3, 10, 0, tzinfo=UTC))
    assert result == {"stale": False, "reason": "before_expected"}


async def test_dst_winter_13_uhr_ortszeit_ist_nach_zwoelf(session: AsyncSession) -> None:
    await _set_expected_by(session, time(12, 0))
    # 12:00 UTC -> 13:00 MEZ.
    result = await run_freshness_check(session, now=datetime(2026, 11, 3, 12, 0, tzinfo=UTC))
    assert result["stale"] is True


async def test_dst_wechseltag_25_10_beide_seiten(session: AsyncSession) -> None:
    """Der Wechseltag selbst: 25.10.2026, Umstellung um 03:00 MESZ.

    Vor der Umstellung gilt UTC+2, danach UTC+1. Ein Vergleich, der die
    Verschiebung nicht kennt, kippt genau hier um eine Stunde. ``ZoneInfo``
    behandelt das transparent — dieser Test belegt es, statt es anzunehmen.
    """
    await _set_expected_by(session, time(12, 0))

    # 09:00 UTC am Wechseltag = 10:00 MEZ (Umstellung um 01:00 UTC bereits
    # vorbei) -> vor 12:00.
    vor = await run_freshness_check(session, now=datetime(2026, 10, 25, 9, 0, tzinfo=UTC))
    assert vor == {"stale": False, "reason": "before_expected"}

    # 12:00 UTC = 13:00 MEZ -> nach 12:00.
    nach = await run_freshness_check(session, now=datetime(2026, 10, 25, 12, 0, tzinfo=UTC))
    assert nach["stale"] is True


# --- Alarmtext -------------------------------------------------------------


async def test_alarmtext_nennt_die_faelligkeit_mit_kuerzel(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Mail wird im Postfach gelesen, ohne die Oberflaeche daneben.

    "bis 12:00 Uhr" waere dort nicht einzuordnen — genau die Luecke, aus der
    der Vorfall vom 26.09. entstanden ist.
    """
    from heizung.services import occupancy_import_service as svc
    from heizung.services import redis_client

    postfach = _Postfach()
    monkeypatch.setattr(svc.mailer, "send_mail", postfach)
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _AlarmRedis())
    await _set_alert_email(session, "chef@example.com")
    await _set_expected_by(session, time(12, 0))

    # 13:00 Ortszeit im Sommer -> Sommerzeit-Kuerzel in der Mail.
    await run_freshness_check(session, now=datetime(2026, 9, 26, 11, 0, tzinfo=UTC))

    assert len(postfach.mails) == 1
    body = postfach.mails[0]["body"]
    assert "12:00" in body
    # Kuerzel plattformabhaengig (MESZ unter deutschem Locale, sonst CEST).
    assert ("MESZ" in body) or ("CEST" in body), body[:200]
