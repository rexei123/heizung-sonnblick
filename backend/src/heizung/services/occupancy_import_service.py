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

from heizung.config import get_settings
from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import OccupancySource
from heizung.models.global_config import GlobalConfig
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.schemas.occupancy_import import (
    OccupancyImportLogResponse,
    OccupancyImportLogRow,
    OccupancyImportPayload,
    resolve_stay_dates,
)
from heizung.services import alert_throttle, mail_status, mailer
from heizung.services.business_audit_service import record_business_action
from heizung.services.occupancy_service import (
    cancel_occupancy_record,
    create_occupancy_record,
    sync_room_status,
)

logger = logging.getLogger(__name__)

# Audit-Actions (OBJEKT_VERB, <=64 Zeichen) — Quelle des Import-Logs.
ACTION_APPLIED = "OCCUPANCY_IMPORT_APPLIED"
ACTION_REJECTED = "OCCUPANCY_IMPORT_REJECTED"
ACTION_CONFLICT = "OCCUPANCY_IMPORT_CONFLICT"
ACTION_STALE = "OCCUPANCY_IMPORT_STALE"
#: Sprint 23 T3: der Abstand zur letzten angewandten Liste ist zu gross.
#: Eigene Aktion und nicht ``ACTION_STALE``: „heute kam keine Liste" und
#: „seit acht Stunden kam keine" sind verschiedene Aussagen, und wer das
#: Audit liest, soll sie unterscheiden koennen.
ACTION_GAP = "OCCUPANCY_IMPORT_GAP"
#: Eine Liste, die **älter** ist als eine bereits angewandte desselben
#: Tages. Seit dem Mehrfachversand (20.10.2026) möglich.
ACTION_OUTDATED = "OCCUPANCY_IMPORT_OUTDATED"
#: Abreise einer laufenden pms-Belegung auf den Listenwert gezogen (19.10.2026).
ACTION_CHECKOUT_CHANGED = "OCCUPANCY_IMPORT_CHECKOUT_CHANGED"
#: Die Liste wollte die Abreise aendern, es wurde **nicht** angewendet.
ACTION_CHECKOUT_SKIPPED = "OCCUPANCY_IMPORT_CHECKOUT_SKIPPED"
TARGET_TYPE = "occupancy_import"

DEFAULT_CHECKIN_LOCAL = time(14, 0)
DEFAULT_CHECKOUT_LOCAL = time(11, 0)

# Fallback, wenn die Singleton-Row fehlt (frische DB ohne Seed). Spiegelt den
# Spalten-Default aus Migration 0022. Casablanca versendet um 10:38 Ortszeit
# (bestaetigt 26.09.2026) — 12:00 laesst gut 80 Minuten Puffer, und eine
# fehlende Liste faellt noch am selben Vormittag auf.
DEFAULT_EXPECTED_BY_LOCAL = time(12, 0)

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
    #: Laufende Belegungen, deren Abreise auf den Listenwert gezogen wurde.
    checkouts_changed: int = 0
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
    """``"09:00"`` -> ``time(9, 0)``. Fallback auf 09:00 bei Murks.

    Seit dem Zeitzonen-Fix (26.09.2026) **nicht mehr im Produktionspfad**:
    die Schwelle kommt als ``time`` direkt aus ``global_config``, es gibt
    keinen String mehr zu parsen. Bleibt als Helfer fuer CLI-Eingaben und
    fuer die Tests, die das Rundum-Verhalten pinnen.
    """
    try:
        hh, mm = value.strip().split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        logger.warning("ungueltiges expected_by_local '%s', Fallback 09:00", value)
        return time(9, 0)


def _fmt_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def tz_abbrev(tz: ZoneInfo, at: datetime) -> str:
    """Zeitzonen-Kuerzel zum Zeitpunkt ``at``, z. B. ``"MESZ"`` / ``"MEZ"``.

    Warum das ueberhaupt gebraucht wird: eine Uhrzeit ohne Einheit ist eine
    Einladung zum Missverstaendnis. Am 26.09.2026 stand in der Oberflaeche
    "08:38" (UTC, ungekennzeichnet) direkt neben "Erwartet bis 09:00 Uhr"
    (Ortszeit, ebenfalls ungekennzeichnet) — zwei Zahlen in verschiedenen
    Einheiten, die wie ein Vergleich aussahen. Die Schwelle wurde daraufhin
    falsch gesetzt, und der Waechter schlug 21 Tage lang zu frueh an.

    ``%Z`` liefert je nach Plattform-Locale "MESZ" oder "CEST". Beides ist
    eindeutig genug; entscheidend ist, dass **ueberhaupt** eine Einheit
    dabeisteht.
    """
    return at.astimezone(tz).strftime("%Z")


def fmt_local_time(t: time, tz: ZoneInfo, at: datetime) -> str:
    """``"12:00 MESZ"`` — Uhrzeit mit Einheit, fuer Mail und API."""
    return f"{_fmt_hhmm(t)} {tz_abbrev(tz, at)}"


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


async def _load_expected_by(session: AsyncSession) -> time:
    """Erwartungszeit der Belegungsliste, **Ortszeit** (Migration 0022).

    Einzige Quelle ist die ``global_config``-Singleton. Die frueher hier
    zustaendige Umgebungsvariable ``OCCUPANCY_IMPORT_EXPECTED_BY_LOCAL`` ist
    entfallen — zwei Quellen fuer denselben Wert waeren ein Drift-Risiko
    (§5.53), und eine Einstellung, die der Hotelier sehen soll, gehoert
    nicht in eine Datei hinter SSH.
    """
    gc = await session.get(GlobalConfig, 1)
    return gc.occupancy_import_expected_by_local if gc is not None else DEFAULT_EXPECTED_BY_LOCAL


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


async def _nicht_angewendet(
    session: AsyncSession,
    *,
    room_id: int,
    grund: str,
    list_date: date,
    request_ip: str | None,
    alt_check_out: datetime | None = None,
    check_out_liste: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Protokolliert eine Listen-Zeile, die **nicht** angewendet wurde.

    Eine Stelle fuer alle Gruende, damit das Audit eine einzige Form hat und
    die Betriebsdoku eine einzige Liste (RUNBOOK §10ag).
    """
    logger.warning(
        "occupancy-import Zeile nicht angewendet (%s) room_id=%s check_out_liste=%s",
        grund,
        room_id,
        check_out_liste.isoformat() if check_out_liste else "-",
    )
    neu: dict[str, Any] = {"grund": grund, "list_date": list_date}
    if check_out_liste is not None:
        neu["check_out_liste"] = check_out_liste
    if extra:
        neu.update(extra)
    await record_business_action(
        session,
        user_id=None,
        action=ACTION_CHECKOUT_SKIPPED,
        target_type="room",
        target_id=room_id,
        old_value=None if alt_check_out is None else {"check_out": alt_check_out},
        new_value=neu,
        request_ip=request_ip,
    )


async def _abreise_nachziehen(
    session: AsyncSession,
    *,
    bestehende: Occupancy,
    neu: _Resolved,
    tz: ZoneInfo,
    now_utc: datetime,
    list_date: date,
    request_ip: str | None,
) -> bool:
    """Zieht ``check_out`` einer laufenden pms-Belegung auf den Listenwert.

    Gibt ``True`` zurueck, wenn tatsaechlich geaendert wurde.

    **Warum es das gibt (Befund 19.10.2026, Zimmer 306).** Phase B1 hat eine
    bestehende Belegung bis dahin uebersprungen. Eine Verlaengerung kam damit
    nie an: die Liste vom 16., 17. und 18.10. trug laengst die richtige
    Abreise, und wir haben sie dreimal verworfen. Das Zimmer galt ab dem
    gemeldeten (falschen) Abreisetag als frei und wurde abgesenkt, waehrend
    der Gast noch zwei Wochen blieb.

    **Dieselbe Buchung — woran?** Die Liste liefert **keine Buchungs-ID**
    (``OccupancyImportEntry``: Zimmer, Anreise, Abreise, Aufenthaltstyp —
    ``schemas/occupancy_import.py``). Es bleibt die **Anreise**, und die
    reicht: zwei Buchungen desselben Zimmers mit gleichem Anreisetag gibt es
    nicht. Verglichen wird der **Kalendertag in Ortszeit**, nicht der
    Zeitstempel — sonst wuerde eine geaenderte Standard-Check-in-Zeit in
    ``global_config`` jede laufende Belegung als fremd erscheinen lassen.

    Das ist genau die Bedingung, die einen **Gaestewechsel am Abreisetag**
    abfaengt: die neue Buchung bringt eine neue Anreise mit, die Anreise
    stimmt nicht ueberein, und die fremde Belegung bleibt unangetastet.

    **Was nicht angewendet wird** (Vorgabe des Betreibers): eine Abreise in
    der Vergangenheit oder vor der Anreise. Beides waere ein Datenfehler in
    der Liste, und die teure Richtung ist hier, einem laufenden Aufenthalt
    das Ende vorzuziehen.
    """
    if bestehende.check_out == neu.check_out:
        return False

    anreise_bestehend = bestehende.check_in.astimezone(tz).date()
    if anreise_bestehend != neu.entry_anreise:
        await _nicht_angewendet(
            session,
            room_id=bestehende.room_id,
            grund="andere_anreise",
            list_date=list_date,
            request_ip=request_ip,
            alt_check_out=bestehende.check_out,
            check_out_liste=neu.check_out,
            extra={
                "anreise_system": anreise_bestehend,
                "anreise_liste": neu.entry_anreise,
            },
        )
        return False

    # Nur noch die vergangene Abreise. Eine **umgedrehte** Zeile (Abreise vor
    # Anreise) kommt hier nicht mehr an: seit B-22-2 vergleicht Phase B1
    # gegen das Buchungsfenster, und ein umgedrehtes Fenster ueberlappt
    # nichts — die Zeile wuerde also am Helfer vorbei bis zum Anlegen
    # durchfallen. Sie wird deshalb **vor** dem Ueberlappungstest abgefangen
    # (siehe dort). Aufgefallen ist das nur, weil der Test dazu schon stand.
    if neu.check_out <= now_utc:
        await _nicht_angewendet(
            session,
            room_id=bestehende.room_id,
            grund="abreise_vergangen",
            list_date=list_date,
            request_ip=request_ip,
            alt_check_out=bestehende.check_out,
            check_out_liste=neu.check_out,
        )
        return False

    alt_check_out = bestehende.check_out
    bestehende.check_out = neu.check_out
    await session.flush()
    # Der Status haengt an der Abreise: eine Verkuerzung auf heute kann das
    # Zimmer sofort frei machen, eine Verlaengerung es belegt halten.
    await sync_room_status(session, bestehende.room_id, now_utc)
    await record_business_action(
        session,
        user_id=None,
        action=ACTION_CHECKOUT_CHANGED,
        target_type="room",
        target_id=bestehende.room_id,
        old_value={"occupancy_id": bestehende.id, "check_out": alt_check_out},
        new_value={
            "occupancy_id": bestehende.id,
            "check_out": neu.check_out,
            "check_in": bestehende.check_in,
            "richtung": "verlaengert" if neu.check_out > alt_check_out else "verkuerzt",
            "list_date": list_date,
        },
        request_ip=request_ip,
    )
    logger.info(
        "occupancy-import abreise nachgezogen room_id=%s alt=%s neu=%s",
        bestehende.room_id,
        alt_check_out.isoformat(),
        neu.check_out.isoformat(),
    )
    return True


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
    checkouts_changed: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    new_value: dict[str, Any] = {
        "external_id": external_id,
        "list_date": list_date,
        "received_at": received_at_utc,
        "rooms_occupied": rooms_occupied,
        "rooms_closed": rooms_closed,
        "conflicts": conflicts,
        "checkouts_changed": checkouts_changed,
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

    # mailparser liefert den Zeitstempel in **UTC** (Befund 26.09.2026, siehe
    # CLAUDE.md §5.79). Bis dahin stand hier ``.replace(tzinfo=tz)`` — das
    # *behauptet* eine Zeitzone, statt umzurechnen, und hat den Eingang damit
    # 21 Tage lang zwei Stunden zu frueh gespeichert.
    #
    # ``list_date`` kommt aus der **Ortszeit** desselben Augenblicks, nicht aus
    # dem UTC-Datum: die Liste gehoert zu dem Kalendertag, den das Hotel
    # gerade hat. Bei einem Versand um 23:30 Ortszeit im Winter waere das
    # UTC-Datum der Vortag.
    received_at_utc = payload.received_at.replace(tzinfo=UTC)
    list_date = received_at_utc.astimezone(tz).date()

    if await _already_processed(session, payload.id, list_date, now_utc):
        return ImportOutcome(
            status="already_processed", external_id=payload.id, list_date=list_date
        )

    # **Reihenfolge-Wache** (Mehrfachversand, 20.10.2026).
    #
    # Seit dem 20.10. kommen drei Listen pro Tag (08:30, 15:30, 19:30). Damit
    # ist die Zustellreihenfolge von Mail und mailparser nicht mehr
    # garantiert — und eine **ältere** Liste, die nach einer neueren
    # eintrifft, würde den älteren Stand erneut anwenden: Phase B2 storniert
    # Zimmer, die die neuere Liste gerade angelegt hat, und
    # ``_abreise_nachziehen`` zieht eine Abreise wieder **zurück** (der
    # Nachzug kennt keine Richtung, er folgt der Liste).
    #
    # Bei **einer** Liste pro Tag konnte das nicht auftreten: zwei Listen
    # desselben Tages gab es nicht. Die Idempotenz oben faengt es nicht, sie
    # prueft ``external_id`` **und** ``list_date`` gemeinsam — und eine
    # zweite Mail hat eine andere Kennung.
    #
    # Gleicher Zeitstempel zaehlt als **nicht neuer**: dann ist es eine
    # Doppel-Zustellung derselben Liste unter neuer Kennung, und die
    # aelteste Entscheidung darf nicht wiederholt werden.
    neuester = await _neuester_eingang_fuer_listentag(session, list_date, now_utc)
    if neuester is not None and received_at_utc <= neuester:
        logger.warning(
            "occupancy-import veraltet: list_date=%s eingang=%s, bereits angewandt bis %s",
            list_date.isoformat(),
            received_at_utc.isoformat(),
            neuester.isoformat(),
        )
        await _record_summary(
            session,
            action=ACTION_OUTDATED,
            external_id=payload.id,
            list_date=list_date,
            received_at_utc=received_at_utc,
            rooms_occupied=0,
            rooms_closed=0,
            conflicts=0,
            result="outdated",
            request_ip=request_ip,
            extra={"bereits_angewandt_bis": neuester},
        )
        await session.commit()
        return ImportOutcome(status="outdated", external_id=payload.id, list_date=list_date)

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
    # Nur noch fuer Phase B2: "welche Belegungen galten an diesem Tag und
    # fehlen jetzt in der Liste". Phase B1 rechnet seit B-22-2 mit dem
    # Fenster der einzelnen Buchung (siehe dort).
    day_start_utc, day_end_utc = _local_day_bounds_utc(list_date, tz)
    affected: set[int] = set()
    rooms_occupied = 0
    conflicts = 0
    checkouts_changed = 0

    # Phase B1: pro Listen-Zimmer anlegen, sofern noch keine aktive pms-
    # Belegung existiert und kein manual-Vorrang greift.
    for r in resolved:
        # Zuerst die Plausibilitaet der Zeile selbst. **Vor** dem
        # Ueberlappungstest, weil ein umgedrehtes Fenster nichts ueberlappt
        # und sonst bis zum Anlegen durchfiele — eine Belegung, die vor ihrem
        # Anfang endet, und jede Statusableitung danach raet.
        #
        # Das Zimmer bleibt dabei in ``target_room_ids``: eine kaputte Zeile
        # darf **nicht** dazu fuehren, dass Phase B2 den laufenden Aufenthalt
        # storniert, weil das Zimmer scheinbar nicht mehr in der Liste steht.
        if r.check_out <= r.check_in:
            await _nicht_angewendet(
                session,
                room_id=r.room_id,
                grund="abreise_vor_anreise",
                list_date=list_date,
                request_ip=request_ip,
                check_out_liste=r.check_out,
                extra={"check_in_liste": r.check_in},
            )
            continue

        # **Gegen das Fenster der Buchung, nicht gegen den Listentag**
        # (B-22-2, 20.10.2026). Bis dahin stand hier ``day_start_utc,
        # day_end_utc``, und das war die Ursache fuer den Gaestewechsel-Fall:
        # die abreisende Belegung endet um 11:00, belegte den Listentag aber
        # bis Mitternacht. Die neue Buchung galt damit als "schon da", wurde
        # uebersprungen und erst am Folgetag angelegt — der neue Gast kam bis
        # zum naechsten Vormittag in ein abgesenktes Zimmer.
        #
        # Mit ``[check_in, check_out)`` der **neuen** Zeile trennen sich die
        # beiden sauber: ``check_out > start`` ist fuer 11:00 gegen 14:00
        # falsch, es gibt keine Ueberlappung, und beide Belegungen stehen
        # nebeneinander ohne sich zu beruehren. Die Ueberlappungs-Invariante
        # bleibt also gewahrt — sie wird sogar schaerfer geprueft als vorher.
        #
        # Fuer Verlaengern und Verkuerzen aendert sich nichts: dort ist es
        # dieselbe Buchung, die Fenster ueberlappen sich, ``bestehende`` wird
        # gefunden und ``_abreise_nachziehen`` entscheidet wie bisher.
        #
        # **Eine Konfigurations-Falle, die dadurch sichtbar wird:** die
        # Uhrzeiten kommen nicht aus der Liste, sondern aus ``global_config``
        # (Vorgabe 14:00 / 11:00). Wer die Check-in-Zeit **vor** die
        # Check-out-Zeit legt, laesst jeden Wechseltag ueberlappen — dann
        # findet B1 die abreisende Belegung wieder, die Anreise stimmt nicht
        # ueberein, und die neue Buchung wird mit ``andere_anreise``
        # abgewiesen statt angelegt. Nicht abgefangen, weil die Einstellung
        # dann auch fuer alles andere unsinnig waere; RUNBOOK §10ag nennt es.
        bestehende = await _active_pms_overlapping(session, r.room_id, r.check_in, r.check_out)
        if bestehende is not None:
            rooms_occupied += 1
            # Seit 19.10.2026: die Abreise wird nachgezogen statt uebersprungen.
            # Vorher endete die Zeile hier mit ``continue``, und eine
            # Verlaengerung kam nie an (Befund Zimmer 306).
            if await _abreise_nachziehen(
                session,
                bestehende=bestehende,
                neu=r,
                tz=tz,
                now_utc=now_utc,
                list_date=list_date,
                request_ip=request_ip,
            ):
                checkouts_changed += 1
                affected.add(r.room_id)
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

        # **Belegungen, die von selbst enden, werden nicht storniert**
        # (Mehrfachversand, 20.10.2026). Zwei Gruende, und der zweite ist der
        # teure.
        #
        # 1. ``check_out`` liegt schon hinter uns. Dann ist der Aufenthalt
        #    vorbei; ein Storno wuerde ihn als **abgebrochen** markieren,
        #    obwehl er regulaer zu Ende ging — und er verschwindet damit aus
        #    dem Zimmer-Verlauf (``room-history-chart.tsx`` filtert
        #    ``cancelled_at``). Bei einer Liste pro Tag um 10:38 trat das nie
        #    auf: die abreisenden Zimmer standen dort noch drin, und 11:00
        #    war noch nicht.
        #
        # 2. ``check_out`` fällt auf den **Listentag**. Das ist der Fall, der
        #    einen Gast betrifft, der noch im Haus ist: die 08:30-Liste kommt
        #    **vor** den Abreisen um 11:00. Fuehrt Casablanca die Abreisenden
        #    dort nicht mehr, waere das Zimmer ab 08:30 als frei geregelt —
        #    abgesenkt, mit jemandem darin, zweieinhalb Stunden lang.
        #
        # **Der Preis, ausdruecklich in Kauf genommen** (Entscheidung des
        # Betreibers vom 20.10.): eine echte **Fruehabreise am Abreisetag**
        # wird nicht vorgezogen. Reist der Gast um 09:00 ab und fehlt in der
        # Liste, heizt das Zimmer bis 11:00 weiter. Zweieinhalb Stunden
        # Komfortwaerme gegen zweieinhalb Stunden Absenkung bei einem
        # anwesenden Gast — die Richtung ist eindeutig.
        #
        # Eine Abreise an einem **frueheren** Tag storniert weiterhin: dort
        # ist der Gast sicher weg, und das Zimmer soll nicht bis zum
        # urspruenglichen Abreisetag heizen.
        if occ.check_out <= now_utc:
            logger.info(
                "occupancy-import B2 verschont room_id=%s (Abreise %s liegt zurueck)",
                occ.room_id,
                occ.check_out.isoformat(),
            )
            continue
        if occ.check_out.astimezone(tz).date() == list_date:
            logger.info(
                "occupancy-import B2 verschont room_id=%s (Abreise %s am Listentag)",
                occ.room_id,
                occ.check_out.isoformat(),
            )
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
        checkouts_changed=checkouts_changed,
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
        checkouts_changed=checkouts_changed,
        external_id=payload.id,
        list_date=list_date,
        affected_room_ids=sorted(affected),
    )


# ---------------------------------------------------------------------------
# Lese-Endpoint (Endpoint B)
# ---------------------------------------------------------------------------


#: Fenster für die gemessene Eingangszeit. Sieben Tage sind lang genug, dass
#: ein einzelner ausgefallener Tag nichts verschiebt, und kurz genug, dass
#: eine Umstellung des Versands binnen einer Woche sichtbar wird.
_EINGANGSZEIT_FENSTER = timedelta(days=7)


async def _frueheste_listenzeit(
    session: AsyncSession, tz: ZoneInfo, now_utc: datetime
) -> time | None:
    """Früheste **Tageszeit**, zu der in den letzten sieben Tagen eine Liste kam.

    Antwortet die Frage, die der Hilfetext auf der API-Seite stellt: wann
    trifft die erste Liste des Tages ein? Bis zum 20.10.2026 stand dort eine
    feste Uhrzeit (``10:38``) — seit dem Mehrfachversand (08:30, 15:30,
    19:30) war sie falsch, und beim nächsten Wechsel des Versands wäre sie
    es wieder (§5.77: eine Zahl im Text, die niemand nachzieht).

    Gezählt wird jede Liste, die **eingetroffen** ist: angewandt, abgewiesen
    (unbekannte Zimmernummer) **oder veraltet**. Alle drei sind angekommen;
    für die Frage "wann kommt Post" ist es unerheblich, ob sie brauchbar war.

    **Die veralteten gehören ausdrücklich dazu**, und das ist nicht
    Vollständigkeit um ihrer selbst willen: eine verspätete 08:30-Liste wird
    genau deshalb abgewiesen, weil sie **zu spät** eintraf — und sie ist
    dabei die **früheste** des Tages. Wer sie wegliesse, würde die Zahl
    systematisch nach hinten verschieben, und zwar in dem Fall, in dem der
    Versand ohnehin schon stolpert. Ein Test hält das fest; aufgefallen ist
    es, weil er zuerst 15:30 statt 08:30 gemeldet hat.

    Genommen wird das **Minimum** über die Tageszeiten, nicht der jüngste
    Wert: gesucht ist, wie früh man mit Post rechnen kann. Ein einzelner
    Ausreißer nach vorn zieht die Zahl damit für sieben Tage mit — das ist
    der Preis dafür, dass ein ausgefallener Nachmittagsversand sie **nicht**
    verschiebt.

    ``None`` heißt "in sieben Tagen kam keine Liste". Das ist kein Fehler,
    sondern der Zustand eines frisch aufgesetzten Systems; der Hilfetext
    sagt dann, dass noch keine da war.
    """
    stmt = (
        select(BusinessAudit)
        .where(
            and_(
                BusinessAudit.action.in_([ACTION_APPLIED, ACTION_REJECTED, ACTION_OUTDATED]),
                BusinessAudit.ts >= now_utc - _EINGANGSZEIT_FENSTER,
            )
        )
        .order_by(desc(BusinessAudit.ts))
    )
    frueheste: time | None = None
    for audit in (await session.execute(stmt)).scalars().all():
        raw = _nv(audit).get("received_at")
        if not isinstance(raw, str):
            continue
        lokal = datetime.fromisoformat(raw).astimezone(tz).time()
        if frueheste is None or lokal < frueheste:
            frueheste = lokal
    return frueheste


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


async def _neuester_eingang_fuer_listentag(
    session: AsyncSession, list_date: date, now_utc: datetime
) -> datetime | None:
    """Der jüngste ``received_at`` der bereits angewandten Läufe **dieses** Tages.

    Unterscheidet sich von :func:`_last_applied_received_at` genau darin: der
    liefert den letzten Erfolg überhaupt (für die Ampel), dieser den letzten
    Erfolg **zu diesem Listentag**. Für die Ampel ist der Tag gleichgültig,
    für die Reihenfolge nicht.

    ``None`` heisst "zu diesem Tag wurde noch nichts angewandt".
    """
    stmt = (
        select(BusinessAudit)
        .where(
            and_(
                BusinessAudit.action == ACTION_APPLIED,
                BusinessAudit.ts >= now_utc - _IDEMPOTENCY_LOOKBACK,
            )
        )
        .order_by(desc(BusinessAudit.ts))
    )
    iso = list_date.isoformat()
    neuester: datetime | None = None
    for audit in (await session.execute(stmt)).scalars().all():
        nv = _nv(audit)
        if nv.get("list_date") != iso:
            continue
        raw = nv.get("received_at")
        if not isinstance(raw, str):
            continue
        eingang = datetime.fromisoformat(raw)
        if neuester is None or eingang > neuester:
            neuester = eingang
    return neuester


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
        # ``.get`` mit Vorgabe: Audit-Zeilen von vor dem 19.10.2026 kennen
        # das Feld nicht, und das Protokoll muss sie weiter anzeigen koennen.
        checkouts_changed=int(nv.get("checkouts_changed", 0)),
        result=nv["result"],
    )


async def get_import_log(
    session: AsyncSession,
    *,
    expected_by_local: time | None = None,
    now: datetime | None = None,
) -> OccupancyImportLogResponse:
    """Baut die Antwort fuer GET .../log inkl. Backend-berechnetem Status.

    :param expected_by_local: Schwelle als **Ortszeit**. ``None`` laedt sie
        aus ``global_config`` — das ist der Produktionspfad; der Parameter
        existiert fuer Tests.
    """
    now_utc = now or datetime.now(tz=UTC)
    tz, _checkin, _checkout = await _load_tz_and_times(session)
    expected_t = expected_by_local or await _load_expected_by(session)

    imports = [_audit_to_logrow(a) for a in await _recent_import_audits(session, limit=30)]
    last_success_at = await _last_applied_received_at(session)
    frueheste = await _frueheste_listenzeit(session, tz, now_utc)
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
        expected_by_local_label=fmt_local_time(expected_t, tz, now_utc),
        first_list_local_label=(
            None if frueheste is None else fmt_local_time(frueheste, tz, now_utc)
        ),
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


async def _send_stale_alert(
    session: AsyncSession,
    *,
    today_local: date,
    expected: time,
    tz: ZoneInfo,
    now_utc: datetime,
) -> None:
    """Alarm-Mail zur ausgebliebenen Belegungsliste (Sprint 18).

    Gebremst ueber ``alert_throttle`` mit dem Listendatum als Gegenstand:
    ein zweiter Watchdog-Lauf am selben Tag legt nicht nach, die taegliche
    Erinnerung bleibt aber erhalten.

    Der Versand ist bewusst ohne ``raise``: bleibt die Mail stecken, ist das
    Audit trotzdem geschrieben und der Watchdog hat seine Aufgabe erfuellt.
    """
    gc = await session.get(GlobalConfig, 1)
    recipient = gc.alert_email if gc is not None else None
    if not recipient:
        return

    if not alert_throttle.should_send(
        alert_throttle.KIND_IMPORT_STALE,
        today_local.isoformat(),
        ttl_s=alert_throttle.TTL_IMPORT_STALE_S,
    ):
        return

    tag = today_local.strftime("%d.%m.%Y")
    # Faelligkeit MIT Kuerzel: die Mail wird im Postfach gelesen, ohne die
    # Oberflaeche daneben. "bis 12:00 Uhr" waere dort nicht einzuordnen.
    faellig = fmt_local_time(expected, tz, now_utc)
    body = "\n".join(
        [
            f"Für den {tag} ist bis {faellig} keine Belegungsliste",
            "eingetroffen.",
            "",
            "Was das System jetzt tut: nichts. Der letzte bekannte Belegungsstand",
            "bleibt eingefroren, es wird kein Zimmer freigegeben und keines belegt.",
            "Die Heizung regelt unverändert weiter.",
            "",
            "Was das heißt: Zimmer, die heute angereist oder abgereist sind, sind dem",
            "System nicht bekannt. Je länger das anhält, desto weiter läuft die",
            "Steuerung an der Wirklichkeit vorbei.",
            "",
            "Wahrscheinlichste Ursachen:",
            "  1. Die Liste wurde heute nicht verschickt.",
            "  2. Der Mail-Weiterleitungsdienst hat sie nicht durchgereicht.",
            "  3. Die Liste kam an, wurde aber abgelehnt — dann steht der Grund",
            "     in der Oberfläche unter Einstellungen / Belegungs-Import.",
            "",
            "Diese Meldung wiederholt sich frühestens morgen.",
        ]
    )
    result = mailer.send_mail(
        recipient=recipient,
        subject=f"Heizung Sonnblick: keine Belegungsliste für {tag}",
        body=body,
    )
    if not result.sent:
        logger.warning(
            "import_stale_mail_nicht_zugestellt",
            extra={"grund": result.reason, "detail": result.detail},
        )

    # T4: Versuch festhalten. Hier wird ausnahmsweise selbst committet: der
    # Aufrufer hat sein Audit schon abgeschlossen (siehe Aufrufstelle), diese
    # Zeilen liegen hinter seinem commit(). Ohne eigenen commit() waere der
    # Vermerk beim Sessionende wieder weg — genau der Fehler aus §5.61.
    await mail_status.record_attempt(session, result)
    await session.commit()


async def _gap_exists_for_list_date(
    session: AsyncSession, list_date: date, now_utc: datetime
) -> bool:
    """Gibt es heute schon einen Abstands-Befund?

    Der Beat laeuft stuendlich; ohne diese Pruefung stuenden bei einem
    laengeren Ausfall fuenf gleichlautende Eintraege im Audit.
    """
    # **Verglichen wird das Listendatum im Eintrag, nicht sein
    # Zeitstempel.** Die erste Fassung filterte auf
    # ``ts BETWEEN tag_beginn AND now`` — und das ist genau die Falle aus
    # §5.59: ``record_business_action`` setzt ``ts`` auf die **echte**
    # Uhrzeit, ein Test mit gestellter Uhr schreibt also einen Eintrag
    # ausserhalb seines eigenen Fensters. Der zweite Lauf fand ihn nicht
    # und legte nach. Im Betrieb waere es nie aufgefallen; der Test hat es
    # gefunden, weil er die Uhr stellt.
    #
    # Dieselbe Form wie ``_stale_exists_for_list_date``: die jüngsten
    # Eintraege lesen und das Datum **im Inhalt** vergleichen. ``limit``
    # statt Zeitfenster — bei einem Eintrag je Tag reichen 20 Zeilen fuer
    # knapp drei Wochen.
    #
    # Der Spaltenname ist ``ts`` und nicht ``created_at``, am Modell
    # nachgesehen (§5.62).
    _ = now_utc  # die Uhr entscheidet hier nichts mehr
    stmt = (
        select(BusinessAudit)
        .where(BusinessAudit.action == ACTION_GAP)
        .where(BusinessAudit.target_type == TARGET_TYPE)
        .order_by(desc(BusinessAudit.ts))
        .limit(20)
    )
    iso = list_date.isoformat()
    for audit in (await session.execute(stmt)).scalars().all():
        if _nv(audit).get("list_date") == iso:
            return True
    return False


async def _send_gap_alert(
    session: AsyncSession,
    *,
    today_local: date,
    last_success_at: datetime,
    stunden: float,
    tz: ZoneInfo,
    now_utc: datetime,
) -> None:
    """Alarm-Mail zum zu grossen Abstand (Sprint 23 T3).

    Eigener Text und nicht der des Stale-Alarms: dort ist **keine** Liste
    gekommen, hier ist eine gekommen und die naechste fehlt. Was der
    Hotelier tun soll, unterscheidet sich — und eine Mail, die den
    falschen Fall beschreibt, kostet den Weg zur Ursache.

    Dieselbe Drosselung wie beim Stale-Alarm, mit demselben Gegenstand
    (dem Listendatum): ein zweiter Lauf am selben Tag legt nicht nach.
    """
    gc = await session.get(GlobalConfig, 1)
    recipient = gc.alert_email if gc is not None else None
    if not recipient:
        return

    if not alert_throttle.should_send(
        alert_throttle.KIND_IMPORT_GAP,
        today_local.isoformat(),
        ttl_s=alert_throttle.TTL_IMPORT_STALE_S,
    ):
        return

    letzte = fmt_local_time(last_success_at.astimezone(tz).time(), tz, now_utc)
    body = "\n".join(
        [
            f"Die letzte Belegungsliste ist vor {stunden:.0f} Stunden eingetroffen",
            f"({letzte}). Seither kam keine weitere.",
            "",
            "Was das System jetzt tut: nichts. Der letzte bekannte Belegungsstand",
            "bleibt eingefroren, es wird kein Zimmer freigegeben und keines belegt.",
            "Die Heizung regelt unverändert weiter.",
            "",
            "Was das heißt: Anreisen und Abreisen, die seit der letzten Liste",
            "dazugekommen sind, sind dem System nicht bekannt. Bei einem",
            "Gästewechsel am selben Tag heizt das Zimmer dann nicht vor.",
            "",
            "Wahrscheinlichste Ursachen:",
            "  1. Die mittägliche oder abendliche Liste wurde nicht verschickt.",
            "  2. Der Mail-Weiterleitungsdienst hat sie nicht durchgereicht.",
            "  3. Die Liste kam an, wurde aber abgelehnt — dann steht der Grund",
            "     in der Oberfläche unter Einstellungen / Belegungs-Import.",
            "",
            "Diese Meldung wiederholt sich frühestens morgen.",
        ]
    )
    result = mailer.send_mail(
        recipient=recipient,
        subject="Heizung Sonnblick: Belegungsliste überfällig",
        body=body,
    )
    if not result.sent:
        logger.warning(
            "import_gap_mail_nicht_zugestellt",
            extra={"grund": result.reason, "detail": result.detail},
        )
    await mail_status.record_attempt(session, result)
    await session.commit()


async def run_freshness_check(
    session: AsyncSession,
    *,
    expected_by_local: time | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prueft, ob heute (Lokal-Datum) bereits ein erfolgreicher Import vorliegt.

    Kein Import nach ``expected_by_local`` -> Audit ``OCCUPANCY_IMPORT_STALE``.
    Gibt KEINE Zimmer frei — der letzte bekannte Stand bleibt eingefroren
    (S5: letzter guter Stand schlaegt Annahme). Idempotent pro Tag.

    Der Vergleich laeuft in **Ortszeit** auf beiden Seiten: ``now_utc`` wird
    ueber ``global_config.timezone`` gewandelt, die Schwelle ist als Wanduhr
    gemeint (§5.65, AE-60). Ein Vergleich gegen ``now_utc.time()`` waere je
    nach Jahreszeit eine oder zwei Stunden daneben.

    :param expected_by_local: Schwelle als Ortszeit. ``None`` laedt sie aus
        ``global_config`` — Produktionspfad; der Parameter ist fuer Tests.
    """
    now_utc = now or datetime.now(tz=UTC)
    tz, _checkin, _checkout = await _load_tz_and_times(session)
    expected = expected_by_local or await _load_expected_by(session)
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

    # Sprint 18 (B-15b-1): Der Alarm geht jetzt wirklich raus. Reihenfolge
    # bewusst NACH dem commit() — nur ein persistiertes Audit loest eine Mail
    # aus. Andernfalls koennte ein Rollback eine Mail hinterlassen, zu der es
    # keinen Eintrag gibt.
    await _send_stale_alert(
        session, today_local=today_local, expected=expected, tz=tz, now_utc=now_utc
    )

    logger.warning(
        "occupancy-import STALE: kein erfolgreicher Import fuer %s bis %s lokal",
        today_local.isoformat(),
        _fmt_hhmm(expected),
    )
    return {"stale": True, "list_date": today_local.isoformat()}


async def run_gap_check(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prueft den **Abstand** zur letzten angewandten Liste (Sprint 23 T3).

    Der taegliche Waechter fragt „kam heute eine Liste?". Fallen die Listen
    um 15:30 und 19:30 aus, bleibt die Ampel gruen (RUNBOOK 10ai): es kam
    ja eine. Dieser Waechter fragt „wie lange ist die letzte her?".

    **Nur innerhalb des Versandfensters.** Zwischen 19:30 und 08:30 liegen
    13 Stunden, und die sind normal — nachts verschickt niemand eine
    Liste. Ohne diese Einschraenkung schlaegt der Waechter jede Nacht an,
    und ein Melder, dem niemand mehr glaubt, ueberwacht nichts (§5.79).

    **Die Schwelle ist 8 h und nicht 3**, und die Begruendung steht in
    ``config.Settings``: die regulaeren Abstaende sind 7 h und 4 h, eine
    Schwelle von 3 h haette jeden Tag um 11:31 angeschlagen. Gemessen an
    den Versandzeiten des Hauses, nicht geschaetzt.

    Gleicher Weg wie der Stale-Alarm: Audit, dann Mail, mit derselben
    Tagesdrosselung. ``None`` als Schwelle schaltet den Waechter ganz aus.

    Gibt **keine** Zimmer frei und aendert keinen Belegungsstand (S5).
    """
    settings = get_settings()
    schwelle = settings.import_max_gap_hours
    if schwelle is None:
        return {"gap": False, "reason": "disabled"}

    now_utc = now or datetime.now(tz=UTC)
    tz, _checkin, _checkout = await _load_tz_and_times(session)
    local_now = now_utc.astimezone(tz)

    fenster_von = settings.import_window_start_local
    fenster_bis = settings.import_window_end_local
    if not (fenster_von <= local_now.time() <= fenster_bis):
        return {"gap": False, "reason": "outside_window"}

    last_success_at = await _last_applied_received_at(session)
    if last_success_at is None:
        # Noch nie eine Liste angewandt. Das ist nicht der Abstand, den
        # dieser Waechter meint — dafuer ist der taegliche Stale-Waechter
        # zustaendig. Zwei Melder fuer denselben Zustand sind einer zu viel.
        return {"gap": False, "reason": "never_imported"}

    abstand = now_utc - last_success_at
    if abstand <= timedelta(hours=schwelle):
        return {"gap": False, "reason": "within_threshold", "hours": abstand / timedelta(hours=1)}

    today_local = local_now.date()
    if await _gap_exists_for_list_date(session, today_local, now_utc):
        return {"gap": True, "already_flagged": True}

    await record_business_action(
        session,
        user_id=None,
        action=ACTION_GAP,
        target_type=TARGET_TYPE,
        target_id=None,
        old_value=None,
        new_value={
            "list_date": today_local.isoformat(),
            "last_success_at": last_success_at.isoformat(),
            "gap_hours": round(abstand / timedelta(hours=1), 1),
            "threshold_hours": schwelle,
        },
    )
    await session.commit()

    # Nach dem commit, wie beim Stale-Alarm: nur ein persistiertes Audit
    # loest eine Mail aus.
    await _send_gap_alert(
        session,
        today_local=today_local,
        last_success_at=last_success_at,
        stunden=abstand / timedelta(hours=1),
        tz=tz,
        now_utc=now_utc,
    )

    logger.warning(
        "occupancy-import GAP: letzte Liste vor %.1f h (Schwelle %d h)",
        abstand / timedelta(hours=1),
        schwelle,
    )
    return {
        "gap": True,
        "list_date": today_local.isoformat(),
        "hours": round(abstand / timedelta(hours=1), 1),
    }
