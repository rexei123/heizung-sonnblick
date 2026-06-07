"""Belegungs-Import-Service (Sprint 15e, AE-66).

Nimmt die taegliche Belegungsliste (Casablanca via mailparser-Webhook)
entgegen und gleicht die ``occupancy``-Tabelle deklarativ ab:

- Listen-Zimmer ohne aktive ``pms``-Belegung -> neu anlegen (source=pms).
- Aktive ``pms``-Belegung, deren Zimmer nicht (mehr) in der Liste steht ->
  schliessen (``is_active=False``), nie loeschen.
- ``manual``-Belegungen werden NIE angefasst; bei Ueberlappung hat manual
  Vorrang (pms-Eintrag wird verworfen + Konflikt-Audit).

Idempotenz, Import-Log und Ampel-Status laufen ueber ``business_audit``
(keine eigene Log-Tabelle, AE-66): Schluessel ist das Paar
``(external_id, list_date)``. Zeiten UTC in DB/API, Europe/Vienna nur fuer
Datums-/Uhrzeit-Ableitung (§5.65).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import OccupancySource
from heizung.models.global_config import GlobalConfig
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.schemas.occupancy_import import (
    OccupancyImportLogResponse,
    OccupancyImportLogRow,
    OccupancyImportPayload,
    resolve_stay_dates,
)
from heizung.services.business_audit_service import record_business_action
from heizung.services.occupancy_service import (
    cancel_occupancy_record,
    create_occupancy_record,
)

logger = logging.getLogger(__name__)

# Audit-Actions (OBJEKT_VERB, <=64 Zeichen) — Quelle des Import-Logs.
ACTION_APPLIED = "OCCUPANCY_IMPORT_APPLIED"
ACTION_REJECTED = "OCCUPANCY_IMPORT_REJECTED"
ACTION_CONFLICT = "OCCUPANCY_IMPORT_CONFLICT"
ACTION_STALE = "OCCUPANCY_IMPORT_STALE"
TARGET_TYPE = "occupancy_import"

DEFAULT_HOTEL_TIMEZONE = "Europe/Vienna"
DEFAULT_CHECKIN_LOCAL = time(14, 0)
DEFAULT_CHECKOUT_LOCAL = time(11, 0)

# Bounded Lookback fuer den Idempotenz-Scan: mailparser-Retries treffen
# innerhalb von Minuten bis Stunden ein, nie Tage spaeter. 7 Tage ist
# grosszuegig und haelt den Scan klein (kein JSONB-SQL noetig).
_IDEMPOTENCY_LOOKBACK = timedelta(days=7)

_ARROW_TOKENS = ("⇒", "=>", "→")


class OccupancyImportRejectedError(Exception):
    """Unbekannte Zimmernummer -> gesamter Request 422, nichts geschrieben.

    Das REJECTED-Audit wurde bereits committed, bevor diese Exception
    geworfen wird (fuer das Import-Log sichtbar).
    """

    def __init__(self, unknown_numbers: list[str]) -> None:
        self.unknown_numbers = unknown_numbers
        super().__init__(f"Unbekannte Zimmernummer(n): {', '.join(unknown_numbers)}")


@dataclass
class ImportOutcome:
    status: str  # "applied" | "already_processed"
    rooms_occupied: int = 0
    rooms_closed: int = 0
    conflicts: int = 0
    external_id: str = ""
    list_date: date | None = None
    affected_room_ids: list[int] = field(default_factory=list)


@dataclass
class _Resolved:
    room_id: int
    check_in: datetime
    check_out: datetime
    entry_anreise: date
    entry_typ: str | None


def parse_target_room(raw: str) -> str:
    """Extrahiert die Ziel-Zimmernummer aus einem ``Zimmer``-Feld.

    Bei Zimmerwechsel (``52⇒101``, ``52 => 101``, mit ``\\n``/Whitespace)
    zaehlt nur das Zielzimmer (Teil nach dem Pfeil). Robust gegen ``⇒``,
    ``=>``, ``→``, Newlines und Mehrfach-Whitespace.
    """
    s = raw
    for token in _ARROW_TOKENS:
        if token in s:
            s = s.rsplit(token, 1)[-1]
    return " ".join(s.split())


def parse_hhmm(value: str) -> time:
    """``"09:00"`` -> ``time(9, 0)``. Fallback auf 09:00 bei Murks."""
    try:
        hh, mm = value.strip().split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        logger.warning("ungueltiges expected_by_local '%s', Fallback 09:00", value)
        return time(9, 0)


def _fmt_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def compute_import_status(
    *,
    now_utc: datetime,
    last_success_at: datetime | None,
    today_received: bool,
    expected_by_local: time,
    tz: ZoneInfo,
) -> str:
    """Ampel-Status (Backend-berechnet, Frontend zeigt nur an).

    - green: heute liegt ein erfolgreicher Import vor, ODER es ist noch vor
      ``expected_by_local`` und der letzte Erfolg ist <= 24 h her.
    - yellow: nach ``expected_by_local``, heute noch kein Import, letzter
      Erfolg <= 24 h her.
    - red: letzter Erfolg > 24 h her, oder nie ein Import.
    """
    if last_success_at is None:
        return "red"
    if today_received:
        return "green"
    if now_utc - last_success_at > timedelta(hours=24):
        return "red"
    local_now_time = now_utc.astimezone(tz).time()
    if local_now_time < expected_by_local:
        return "green"
    return "yellow"


# ---------------------------------------------------------------------------
# interne Helfer
# ---------------------------------------------------------------------------


def _nv(audit: BusinessAudit) -> dict[str, Any]:
    """``new_value`` ist immer ein Dict (wir schreiben nur Dicts)."""
    return cast(dict[str, Any], audit.new_value)


async def _load_tz_and_times(session: AsyncSession) -> tuple[ZoneInfo, time, time]:
    gc = await session.get(GlobalConfig, 1)
    if gc is None:
        return (
            ZoneInfo(DEFAULT_HOTEL_TIMEZONE),
            DEFAULT_CHECKIN_LOCAL,
            DEFAULT_CHECKOUT_LOCAL,
        )
    return ZoneInfo(gc.timezone), gc.default_checkin_time, gc.default_checkout_time


def _local_day_bounds_utc(list_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(list_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


async def _room_id_by_number(session: AsyncSession, number: str) -> int | None:
    room_id: int | None = await session.scalar(select(Room.id).where(Room.number == number))
    return room_id


async def _active_pms_overlapping(
    session: AsyncSession, room_id: int, start_utc: datetime, end_utc: datetime
) -> Occupancy | None:
    stmt = (
        select(Occupancy)
        .where(
            and_(
                Occupancy.room_id == room_id,
                Occupancy.is_active.is_(True),
                Occupancy.source == OccupancySource.PMS,
                Occupancy.check_in < end_utc,
                Occupancy.check_out > start_utc,
            )
        )
        .limit(1)
    )
    occ: Occupancy | None = await session.scalar(stmt)
    return occ


async def _all_active_pms_overlapping(
    session: AsyncSession, start_utc: datetime, end_utc: datetime
) -> list[Occupancy]:
    stmt = select(Occupancy).where(
        and_(
            Occupancy.is_active.is_(True),
            Occupancy.source == OccupancySource.PMS,
            Occupancy.check_in < end_utc,
            Occupancy.check_out > start_utc,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _active_manual_overlapping(
    session: AsyncSession, room_id: int, check_in: datetime, check_out: datetime
) -> bool:
    stmt = (
        select(Occupancy.id)
        .where(
            and_(
                Occupancy.room_id == room_id,
                Occupancy.is_active.is_(True),
                Occupancy.source == OccupancySource.MANUAL,
                Occupancy.check_in < check_out,
                Occupancy.check_out > check_in,
            )
        )
        .limit(1)
    )
    return await session.scalar(stmt) is not None


async def _record_summary(
    session: AsyncSession,
    *,
    action: str,
    external_id: str,
    list_date: date,
    received_at_utc: datetime,
    rooms_occupied: int,
    rooms_closed: int,
    conflicts: int,
    result: str,
    request_ip: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    new_value: dict[str, Any] = {
        "external_id": external_id,
        "list_date": list_date,
        "received_at": received_at_utc,
        "rooms_occupied": rooms_occupied,
        "rooms_closed": rooms_closed,
        "conflicts": conflicts,
        "result": result,
    }
    if extra:
        new_value.update(extra)
    await record_business_action(
        session,
        user_id=None,  # System-Trigger (Webhook), kein eingeloggter User
        action=action,
        target_type=TARGET_TYPE,
        target_id=None,
        old_value=None,
        new_value=new_value,
        request_ip=request_ip,
    )


async def _already_processed(
    session: AsyncSession, external_id: str, list_date: date, now_utc: datetime
) -> bool:
    stmt = (
        select(BusinessAudit)
        .where(
            and_(
                BusinessAudit.action.in_([ACTION_APPLIED, ACTION_REJECTED]),
                BusinessAudit.ts >= now_utc - _IDEMPOTENCY_LOOKBACK,
            )
        )
        .order_by(desc(BusinessAudit.ts))
    )
    iso = list_date.isoformat()
    for audit in (await session.execute(stmt)).scalars().all():
        nv = _nv(audit)
        if nv.get("external_id") == external_id and nv.get("list_date") == iso:
            return True
    return False


# ---------------------------------------------------------------------------
# Import (Endpoint A)
# ---------------------------------------------------------------------------


async def reconcile_from_import(
    session: AsyncSession,
    *,
    payload: OccupancyImportPayload,
    request_ip: str | None = None,
    now: datetime | None = None,
) -> ImportOutcome:
    """Deklarativer Abgleich der ``occupancy``-Tabelle aus einer Tagesliste.

    Committed selbst. Engine-Re-Eval der betroffenen Raeume obliegt dem
    Aufrufer (``affected_room_ids``). Wirft ``OccupancyImportRejectedError`` bei
    unbekannter Zimmernummer (nichts an Belegungen geschrieben).
    """
    now_utc = now or datetime.now(tz=UTC)
    tz, checkin_t, checkout_t = await _load_tz_and_times(session)

    list_date = payload.received_at.date()
    received_at_utc = payload.received_at.replace(tzinfo=tz).astimezone(UTC)

    if await _already_processed(session, payload.id, list_date, now_utc):
        return ImportOutcome(
            status="already_processed", external_id=payload.id, list_date=list_date
        )

    # Phase A: alle Zimmernummern aufloesen (atomar — unbekannte -> REJECT).
    resolved: list[_Resolved] = []
    unknown: list[str] = []
    for entry in payload.liste:
        number = parse_target_room(entry.zimmer)
        room_id = await _room_id_by_number(session, number)
        if room_id is None:
            unknown.append(number)
            continue
        anreise_date, abreise_date = resolve_stay_dates(entry.anreise, entry.abreise, list_date)
        check_in = datetime.combine(anreise_date, checkin_t, tzinfo=tz).astimezone(UTC)
        check_out = datetime.combine(abreise_date, checkout_t, tzinfo=tz).astimezone(UTC)
        resolved.append(
            _Resolved(
                room_id=room_id,
                check_in=check_in,
                check_out=check_out,
                entry_anreise=anreise_date,
                entry_typ=entry.aufenthaltstyp,
            )
        )

    if unknown:
        await _record_summary(
            session,
            action=ACTION_REJECTED,
            external_id=payload.id,
            list_date=list_date,
            received_at_utc=received_at_utc,
            rooms_occupied=0,
            rooms_closed=0,
            conflicts=0,
            result="rejected",
            request_ip=request_ip,
            extra={"unknown_numbers": unknown},
        )
        await session.commit()
        raise OccupancyImportRejectedError(unknown)

    target_room_ids = {r.room_id for r in resolved}
    day_start_utc, day_end_utc = _local_day_bounds_utc(list_date, tz)
    affected: set[int] = set()
    rooms_occupied = 0
    conflicts = 0

    # Phase B1: pro Listen-Zimmer anlegen, sofern noch keine aktive pms-
    # Belegung existiert und kein manual-Vorrang greift.
    for r in resolved:
        if await _active_pms_overlapping(session, r.room_id, day_start_utc, day_end_utc):
            rooms_occupied += 1
            continue
        if await _active_manual_overlapping(session, r.room_id, r.check_in, r.check_out):
            conflicts += 1
            await record_business_action(
                session,
                user_id=None,
                action=ACTION_CONFLICT,
                target_type="room",
                target_id=r.room_id,
                old_value=None,
                new_value={"room_id": r.room_id, "list_date": list_date},
                request_ip=request_ip,
            )
            continue
        await create_occupancy_record(
            session,
            room_id=r.room_id,
            check_in=r.check_in,
            check_out=r.check_out,
            guest_count=None,
            source=OccupancySource.PMS,
            external_id=payload.id,
            now=now_utc,
        )
        rooms_occupied += 1
        affected.add(r.room_id)

    # Phase B2: aktive pms-Belegungen fuer list_date, deren Zimmer NICHT in
    # der Liste steht -> schliessen (Hotel-Auszug / nicht mehr belegt).
    rooms_closed = 0
    for occ in await _all_active_pms_overlapping(session, day_start_utc, day_end_utc):
        if occ.room_id in target_room_ids:
            continue
        await cancel_occupancy_record(session, occ, now=now_utc)
        rooms_closed += 1
        affected.add(occ.room_id)

    await _record_summary(
        session,
        action=ACTION_APPLIED,
        external_id=payload.id,
        list_date=list_date,
        received_at_utc=received_at_utc,
        rooms_occupied=rooms_occupied,
        rooms_closed=rooms_closed,
        conflicts=conflicts,
        result="applied",
        request_ip=request_ip,
    )
    await session.commit()

    # Aufenthaltstyp + Anreise nur als Kreuzcheck loggen, NICHT Steuergroesse.
    for r in resolved:
        logger.info(
            "occupancy-import cross-check room_id=%s anreise=%s aufenthaltstyp=%s",
            r.room_id,
            r.entry_anreise.isoformat(),
            r.entry_typ,
        )

    return ImportOutcome(
        status="applied",
        rooms_occupied=rooms_occupied,
        rooms_closed=rooms_closed,
        conflicts=conflicts,
        external_id=payload.id,
        list_date=list_date,
        affected_room_ids=sorted(affected),
    )


# ---------------------------------------------------------------------------
# Lese-Endpoint (Endpoint B)
# ---------------------------------------------------------------------------


async def _recent_import_audits(session: AsyncSession, limit: int) -> list[BusinessAudit]:
    stmt = (
        select(BusinessAudit)
        .where(BusinessAudit.action.in_([ACTION_APPLIED, ACTION_REJECTED]))
        .order_by(desc(BusinessAudit.ts))
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _last_applied_received_at(session: AsyncSession) -> datetime | None:
    stmt = (
        select(BusinessAudit)
        .where(BusinessAudit.action == ACTION_APPLIED)
        .order_by(desc(BusinessAudit.ts))
        .limit(1)
    )
    audit = await session.scalar(stmt)
    if audit is None:
        return None
    raw = _nv(audit).get("received_at")
    return datetime.fromisoformat(raw) if isinstance(raw, str) else None


async def _applied_exists_for_list_date(
    session: AsyncSession, list_date: date, now_utc: datetime
) -> bool:
    stmt = (
        select(BusinessAudit)
        .where(
            and_(
                BusinessAudit.action == ACTION_APPLIED,
                BusinessAudit.ts >= now_utc - timedelta(days=2),
            )
        )
        .order_by(desc(BusinessAudit.ts))
    )
    iso = list_date.isoformat()
    for audit in (await session.execute(stmt)).scalars().all():
        if _nv(audit).get("list_date") == iso:
            return True
    return False


def _audit_to_logrow(audit: BusinessAudit) -> OccupancyImportLogRow:
    nv = _nv(audit)
    return OccupancyImportLogRow(
        received_at=datetime.fromisoformat(nv["received_at"]),
        list_date=date.fromisoformat(nv["list_date"]),
        external_id=nv["external_id"],
        rooms_occupied=nv["rooms_occupied"],
        rooms_closed=nv["rooms_closed"],
        conflicts=nv["conflicts"],
        result=nv["result"],
    )


async def get_import_log(
    session: AsyncSession,
    *,
    expected_by_local_str: str,
    now: datetime | None = None,
) -> OccupancyImportLogResponse:
    """Baut die Antwort fuer GET .../log inkl. Backend-berechnetem Status."""
    now_utc = now or datetime.now(tz=UTC)
    tz, _checkin, _checkout = await _load_tz_and_times(session)
    expected_t = parse_hhmm(expected_by_local_str)

    imports = [_audit_to_logrow(a) for a in await _recent_import_audits(session, limit=30)]
    last_success_at = await _last_applied_received_at(session)
    today_local = now_utc.astimezone(tz).date()
    today_received = await _applied_exists_for_list_date(session, today_local, now_utc)

    status = compute_import_status(
        now_utc=now_utc,
        last_success_at=last_success_at,
        today_received=today_received,
        expected_by_local=expected_t,
        tz=tz,
    )
    return OccupancyImportLogResponse(
        status=status,
        last_success_at=last_success_at,
        expected_by_local=_fmt_hhmm(expected_t),
        today_received=today_received,
        imports=imports,
    )


# ---------------------------------------------------------------------------
# Staleness-Watchdog (Celery-Beat)
# ---------------------------------------------------------------------------


async def _stale_exists_for_list_date(
    session: AsyncSession, list_date: date, now_utc: datetime
) -> bool:
    stmt = (
        select(BusinessAudit)
        .where(
            and_(
                BusinessAudit.action == ACTION_STALE,
                BusinessAudit.ts >= now_utc - timedelta(days=2),
            )
        )
        .order_by(desc(BusinessAudit.ts))
    )
    iso = list_date.isoformat()
    for audit in (await session.execute(stmt)).scalars().all():
        if _nv(audit).get("list_date") == iso:
            return True
    return False


async def run_freshness_check(
    session: AsyncSession,
    *,
    expected_by_local_str: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prueft, ob heute (Lokal-Datum) bereits ein erfolgreicher Import vorliegt.

    Kein Import nach ``expected_by_local`` -> Audit ``OCCUPANCY_IMPORT_STALE``.
    Gibt KEINE Zimmer frei — der letzte bekannte Stand bleibt eingefroren
    (S5: letzter guter Stand schlaegt Annahme). Idempotent pro Tag.
    """
    now_utc = now or datetime.now(tz=UTC)
    tz, _checkin, _checkout = await _load_tz_and_times(session)
    expected = parse_hhmm(expected_by_local_str)
    local_now = now_utc.astimezone(tz)

    if local_now.time() < expected:
        return {"stale": False, "reason": "before_expected"}

    today_local = local_now.date()
    if await _applied_exists_for_list_date(session, today_local, now_utc):
        return {"stale": False, "reason": "import_present"}
    if await _stale_exists_for_list_date(session, today_local, now_utc):
        return {"stale": True, "already_flagged": True}

    await record_business_action(
        session,
        user_id=None,
        action=ACTION_STALE,
        target_type=TARGET_TYPE,
        target_id=None,
        old_value=None,
        new_value={"list_date": today_local, "reason": "no_import_by_expected"},
    )
    await session.commit()

    # Email-Alarm absichtlich NICHT implementiert — an B-15b-1 (Email-Service)
    # gekoppelt. Sobald B-15b-1 live ist: hier global_config.alert_email
    # triggern. Schalter steht bereit, kein Versand in Sprint 15e.
    logger.warning(
        "occupancy-import STALE: kein erfolgreicher Import fuer %s bis %s lokal",
        today_local.isoformat(),
        _fmt_hhmm(expected),
    )
    return {"stale": True, "list_date": today_local.isoformat()}
