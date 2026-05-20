"""Manual-Override-Domain-Logik (Sprint 9.9 + Sprint 12a-Konsolidierung, AE-58).

Reine Domain-Schicht: kennt KEIN Casablanca, KEIN Vicki, KEIN HTTP. Nimmt
``AsyncSession`` + Werte, gibt Modelle zurueck. Konsumenten:

- ``api/v1/overrides``                 -> create / get_active / get_history / revoke (T4)
- ``services/device_adapter``          -> create(source=DEVICE) (T5)
- Casablanca-Sync-Job                  -> revoke_all_active_overrides (Sprint 12a T2/T6)
- ``tasks/cleanup_overrides``          -> cleanup_expired (T7)
- Engine Layer 3                       -> get_active (T3)

Sprint 12a hat die Domain konsolidiert (AE-58): Override gilt nur in
OCCUPIED-Zimmern (``RoomNotOccupiedError`` Pre-Insert-Gate), Zone-Scope
optional via ``heating_zone_id``, Check-out revoked ALLE Quellen
(``revoke_all_active_overrides`` ersetzt ``revoke_device_overrides``).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import OverrideSource, RoomStatus
from heizung.models.global_config import GlobalConfig
from heizung.models.manual_override import ManualOverride
from heizung.rules.window_state import detect_open_window_zones
from heizung.services.occupancy_service import derive_room_status

logger = logging.getLogger(__name__)

MIN_SETPOINT = Decimal("5.0")
MAX_SETPOINT = Decimal("30.0")
HARD_MAX_DURATION_DAYS = 7
HISTORY_LIMIT_CAP = 200
DEFAULT_TIMEZONE = "Europe/Vienna"


class OverrideRejectedWindowOpenError(Exception):
    """Sprint 12 T4 (AE-52): Override-Anlage wird abgewiesen, wenn
    mindestens eine HeatingZone des Raums ein offenes Fenster meldet.

    AE-52-Wortlaut: „Override-Eingabe wird ignoriert — nicht gespeichert,
    nicht angewendet, nicht nach Fenster-Schliessen reaktiviert."
    Implementiert als hartes Reject im Service: kein DB-Insert, kein
    Audit-Eintrag. API-Layer mappt auf HTTP 409.

    Bewusst in diesem Modul (nicht in einem generischen
    ``exceptions.py``), damit die Fehler-Klasse zur Domain ``override``
    gehoert und der API-Layer sie aus dem gleichen Import-Pfad
    bekommt wie die Funktion, die sie wirft.

    :param zones: Liste der offenen Zonen aus
        ``rules.window_state.detect_open_window_zones`` — wird vom
        API-Layer als Teil des 409-Response-Bodys gerendert
        (zone_id ist pflicht, reading_at optional).
    """

    def __init__(self, zones: list[dict[str, Any]]) -> None:
        self.zones = zones
        zone_ids = [z.get("zone_id") for z in zones]
        super().__init__(
            f"Override-Anlage abgewiesen: Fenster offen in Zone(n) {zone_ids}. "
            "Bitte Fenster schliessen und erneut versuchen."
        )


class RoomNotOccupiedError(Exception):
    """Sprint 12a T2 (AE-58): Override-Anlage wird abgewiesen, wenn der Raum
    nicht ``OCCUPIED`` ist.

    AE-58: Override existiert nur in OCCUPIED-Zimmern; VACANT/RESERVED/
    CLEANING/BLOCKED laufen auf globalen Einstellungen + Frostschutz, keine
    Override-Ausnahmen. Vicki-Drehring in VACANT ist Daten-Anomalie und
    wird vom Device-Pfad (T4) silent geskippt; Frontend-Pfad (T3) mappt
    auf HTTP 409 ``room_not_occupied``.

    :param room_id: betroffener Raum.
    :param status: aktueller abgeleiteter Status (aus ``derive_room_status``).
    """

    def __init__(self, room_id: int, status: RoomStatus) -> None:
        self.room_id = room_id
        self.status = status
        super().__init__(
            f"Override-Anlage abgewiesen: Raum {room_id} ist nicht OCCUPIED "
            f"(Status: {status.value}). Override gilt nur fuer belegte Raeume."
        )


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _quantize(setpoint: Decimal) -> Decimal:
    return setpoint.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)


def _hard_cap(expires_at: datetime, now: datetime) -> tuple[datetime, bool]:
    """Cappt ``expires_at`` auf ``now + HARD_MAX_DURATION_DAYS``.

    Returns ``(capped_value, was_capped)``.
    """
    hard_max = now + timedelta(days=HARD_MAX_DURATION_DAYS)
    if expires_at > hard_max:
        return hard_max, True
    return expires_at, False


def compute_expires_at(
    source: OverrideSource,
    now: datetime,
    *,
    next_checkout_at: datetime | None = None,
    hotel_config: GlobalConfig | None = None,
) -> datetime:
    """Default-Ablauf je Quelle, anschliessend 7-Tage-Hard-Cap.

    - ``frontend_4h``        -> ``now + 4 h``
    - ``frontend_midnight``  -> ``heute 23:59`` Hotel-Timezone (aus
      ``hotel_config.timezone``, sonst Europe/Vienna).
    - ``frontend_checkout``  -> ``next_checkout_at`` falls gesetzt,
      sonst ``now + 7 Tage``.
    - ``device``             -> identisch zu ``frontend_checkout``.

    ``hotel_config`` ist eine ``GlobalConfig``-Singleton-Instanz; der
    Parameter heisst ``hotel_config`` (Plan-Wording), Typ ist projekt-
    seitig ``GlobalConfig``. Multi-Hotel kommt erst Sprint 11+.
    """
    if source == OverrideSource.FRONTEND_4H:
        raw = now + timedelta(hours=4)
    elif source == OverrideSource.FRONTEND_MIDNIGHT:
        tz_name = hotel_config.timezone if hotel_config is not None else DEFAULT_TIMEZONE
        tz = ZoneInfo(tz_name)
        local_now = now.astimezone(tz)
        local_midnight = local_now.replace(hour=23, minute=59, second=0, microsecond=0)
        raw = local_midnight.astimezone(UTC)
    elif source in (OverrideSource.FRONTEND_CHECKOUT, OverrideSource.DEVICE):
        # Sprint 12a T2 (AE-58): Fallback-Pfad ``now+7d`` entfaellt. Mit
        # vorgeschaltetem OCCUPIED-Gate (siehe ``create``) gibt es immer
        # eine aktive Belegung, also liefert ``next_active_checkout`` einen
        # Wert. ``None`` ist ein Contract-Bruch beim Aufrufer; defensiv
        # raisen damit der Fehler an die Oberflaeche kommt, statt still
        # auf 7 Tage zu cappen.
        if next_checkout_at is None:
            raise ValueError(
                f"next_checkout_at darf nicht None sein fuer source={source.value} "
                "— OCCUPIED-Gate haette das verhindern muessen"
            )
        raw = next_checkout_at
    else:
        raise ValueError(f"Unbekannte OverrideSource: {source}")

    capped, _ = _hard_cap(raw, now)
    return capped


async def create(
    session: AsyncSession,
    *,
    room_id: int,
    setpoint: Decimal,
    source: OverrideSource,
    expires_at: datetime,
    reason: str | None = None,
    created_by: str | None = None,
    heating_zone_id: int | None = None,
) -> ManualOverride:
    """Legt einen neuen Override an.

    Sprint 12a T2 (AE-58): zwei Pre-Insert-Gates in dieser Reihenfolge:

    1. **OCCUPIED-Gate** — Override gilt nur fuer belegte Raeume. Status
       wird via ``derive_room_status`` aus aktiven Occupancies berechnet
       (canonical, nicht stale ``room.status``-Feld).
    2. **Window-Offen-Gate** (Sprint 12 T4 / AE-52) — Override wird
       abgewiesen, wenn mindestens eine HeatingZone des Raums
       ``open_window=True`` meldet.

    :param heating_zone_id: optionale Zone-Granularitaet (Sprint 12a T1/T2).
        ``None`` = Room-Scope-Override (Backward-Compat fuer Aufrufer
        ohne Zone-Wissen). Engine Layer 3 (T5) priorisiert Zone-Match vor
        Room-Match beim Lookup.
    :raises ValueError: setpoint out-of-range [MIN_SETPOINT, MAX_SETPOINT].
    :raises RoomNotOccupiedError: Sprint 12a T2 (AE-58) — Raum ist nicht
        OCCUPIED. Override wird NICHT persistiert.
    :raises OverrideRejectedWindowOpenError: Sprint 12 T4 (AE-52) — eine
        oder mehrere HeatingZones des Raums melden gerade ``open_window=
        True`` mit frischem Reading. Override wird NICHT persistiert.
    """
    quantized = _quantize(setpoint)
    if quantized < MIN_SETPOINT or quantized > MAX_SETPOINT:
        raise ValueError(
            f"Setpoint {quantized} liegt ausserhalb [{MIN_SETPOINT}, {MAX_SETPOINT}] degC"
        )

    now = _now()

    # Sprint 12a T2 (AE-58): OCCUPIED-Gate VOR Window-Gate. AE-58 verankert
    # Override-Domain als „nur fuer belegte Raeume"; VACANT/RESERVED/CLEANING/
    # BLOCKED laufen auf globalen Einstellungen + Frostschutz, keine Override-
    # Ausnahmen. ``derive_room_status`` ist die canonical Quelle (aus aktiven
    # Occupancies abgeleitet), ``room.status``-Feld koennte stale sein.
    room_status = await derive_room_status(session, room_id, now)
    if room_status != RoomStatus.OCCUPIED:
        raise RoomNotOccupiedError(room_id, room_status)

    # Sprint 12 T4 (AE-52): Pre-Insert Window-Check. Wenn mindestens eine
    # Zone des Raums Fenster offen meldet, wird der Override abgewiesen
    # OHNE DB-Insert. Brief-Wortlaut: „nicht gespeichert, nicht angewendet,
    # nicht nach Fenster-Schliessen reaktiviert". Engine-Maskierung (T3)
    # gilt nur fuer bestehende Overrides; T4 ist die symmetrische Reject-
    # Logik fuer neu angelegte Overrides.
    open_zones = await detect_open_window_zones(session, room_id, now)
    if open_zones:
        raise OverrideRejectedWindowOpenError(open_zones)

    capped_expires_at, was_capped = _hard_cap(expires_at, now)
    if was_capped:
        # TODO Sprint 9.9 Backlog: dedizierter event_log-Eintrag fuer Cap-Events.
        # Bestehender ``services.event_log``-Wrapper existiert nicht; ein
        # direkter ``EventLog(...)``-Insert ausserhalb der Engine-Pipeline
        # erfordert kuenstliche evaluation_id/layer-Werte. Vorerst nur Log.
        logger.warning(
            "manual_override hard-capped: room_id=%s source=%s requested=%s capped=%s",
            room_id,
            source.value,
            expires_at.isoformat(),
            capped_expires_at.isoformat(),
        )

    override = ManualOverride(
        room_id=room_id,
        heating_zone_id=heating_zone_id,
        setpoint=quantized,
        source=source,
        expires_at=capped_expires_at,
        reason=reason,
        created_by=created_by,
    )
    session.add(override)
    await session.flush()
    return override


async def get_active(
    session: AsyncSession,
    room_id: int,
    heating_zone_id: int | None = None,
) -> ManualOverride | None:
    """Aktiver Override fuer den Raum (Sprint 12a T2, AE-58).

    Lookup-Priorisierung (Sprint 12a):

    1. **Scope:** Wenn ``heating_zone_id`` gesetzt, gewinnt Zone-Match
       (``heating_zone_id == X``) vor Room-Match (``heating_zone_id IS NULL``).
       Ohne ``heating_zone_id`` werden ausschliesslich Room-Scope-Overrides
       betrachtet — Zone-Overrides bleiben unsichtbar (Backward-Compat fuer
       Aufrufer ohne Zone-Wissen, z.B. Legacy-Engine-Layer-3-Pfad vor T5).
    2. **Quelle:** FRONTEND_* schlaegt DEVICE (Mitarbeiter > Gast).
    3. **Tiebreaker:** ``created_at DESC`` (neuerer Eintrag gewinnt).
    """
    now = _now()
    is_device = case(
        (ManualOverride.source == OverrideSource.DEVICE, 1),
        else_=0,
    )
    base = (
        select(ManualOverride)
        .where(ManualOverride.room_id == room_id)
        .where(ManualOverride.revoked_at.is_(None))
        .where(ManualOverride.expires_at > now)
    )
    if heating_zone_id is None:
        stmt = (
            base.where(ManualOverride.heating_zone_id.is_(None))
            .order_by(is_device, ManualOverride.created_at.desc())
            .limit(1)
        )
    else:
        is_room_scope = case(
            (ManualOverride.heating_zone_id.is_(None), 1),
            else_=0,
        )
        stmt = (
            base.where(
                or_(
                    ManualOverride.heating_zone_id == heating_zone_id,
                    ManualOverride.heating_zone_id.is_(None),
                )
            )
            .order_by(is_room_scope, is_device, ManualOverride.created_at.desc())
            .limit(1)
        )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_history(
    session: AsyncSession,
    room_id: int,
    *,
    limit: int = 50,
    include_expired: bool = True,
    heating_zone_id: int | None = None,
) -> list[ManualOverride]:
    """Override-Historie fuer den Raum.

    Ohne ``heating_zone_id`` (Default, Backward-Compat): alle Overrides des
    Raums, ``created_at DESC``.

    Mit ``heating_zone_id``: Zone-Match (``heating_zone_id == X``) plus
    Room-Scope-Overrides (``heating_zone_id IS NULL``) als Fallback im
    Response. Sortierung: Zone-Match zuerst (Block oben), dann Room-Match,
    dann ``created_at DESC`` innerhalb jedes Blocks (Sprint 12a T3).

    ``limit`` wird auf ``HISTORY_LIMIT_CAP`` (= 200) gekappt.
    """
    effective_limit = min(limit, HISTORY_LIMIT_CAP)
    base = select(ManualOverride).where(ManualOverride.room_id == room_id)
    if heating_zone_id is None:
        stmt = base.order_by(ManualOverride.created_at.desc()).limit(effective_limit)
    else:
        is_room_scope = case(
            (ManualOverride.heating_zone_id.is_(None), 1),
            else_=0,
        )
        stmt = (
            base.where(
                or_(
                    ManualOverride.heating_zone_id == heating_zone_id,
                    ManualOverride.heating_zone_id.is_(None),
                )
            )
            .order_by(is_room_scope, ManualOverride.created_at.desc())
            .limit(effective_limit)
        )
    if not include_expired:
        now = _now()
        stmt = stmt.where(ManualOverride.expires_at > now)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def revoke(
    session: AsyncSession,
    override_id: int,
    *,
    reason: str | None = None,
) -> ManualOverride:
    """Setzt ``revoked_at = now()``. ``ValueError`` bei doppeltem Revoke."""
    override = await session.get(ManualOverride, override_id)
    if override is None:
        raise ValueError(f"ManualOverride id={override_id} existiert nicht")
    if override.revoked_at is not None:
        raise ValueError(f"ManualOverride id={override_id} ist bereits revoked")
    override.revoked_at = _now()
    override.revoked_reason = reason
    await session.flush()
    return override


async def revoke_all_active_overrides(
    session: AsyncSession,
    room_id: int,
    *,
    reason: str = "auto: guest checked out",
) -> int:
    """Revoked ALLE aktiven Overrides des Raums (Sprint 12a T2, AE-58).

    Sprint 12a hat ``revoke_device_overrides`` ersatzlos durch diese
    Funktion ersetzt. Bei Check-out (PMS-Hook, OCCUPIED -> VACANT ohne
    Folge-Checkin in 4h) wird der komplette Override-Stack des Raums
    revokiert — DEVICE und FRONTEND_*. Grund: ein neuer Gast soll auf
    globalen Einstellungen starten, ohne dass alte Mitarbeiter-Overrides
    aus der vorigen Belegung weiterlaufen.

    Filter: ``revoked_at IS NULL AND expires_at > now``, kein
    ``source``-Filter mehr.

    Returns Anzahl der revokierten Overrides.
    """
    now = _now()
    stmt = (
        select(ManualOverride)
        .where(ManualOverride.room_id == room_id)
        .where(ManualOverride.revoked_at.is_(None))
        .where(ManualOverride.expires_at > now)
    )
    result = await session.execute(stmt)
    overrides = list(result.scalars().all())
    for override in overrides:
        override.revoked_at = now
        override.revoked_reason = reason
    if overrides:
        await session.flush()
    return len(overrides)


async def cleanup_expired(session: AsyncSession) -> int:
    """Markiert alle nicht-revokierten, abgelaufenen Overrides als revoked.

    Wird vom celery_beat-Task in T7 taeglich aufgerufen. Returns count.
    """
    now = _now()
    stmt = (
        select(ManualOverride)
        .where(ManualOverride.revoked_at.is_(None))
        .where(ManualOverride.expires_at < now)
    )
    result = await session.execute(stmt)
    overrides = list(result.scalars().all())
    for override in overrides:
        override.revoked_at = override.expires_at
        override.revoked_reason = "auto: expired"
    if overrides:
        await session.flush()
    return len(overrides)
