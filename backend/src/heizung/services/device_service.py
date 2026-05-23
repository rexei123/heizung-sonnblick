"""Device-Lifecycle-Service (Sprint 13b.1, AE-57).

Single Source of Truth fuer Device-Lifecycle-Operationen:

- ``get_active_devices_for_zone`` + ``get_pool_devices`` — Lese-Helper
  fuer ``retired_at IS NULL``-Filter (T3, §L-Stellen).
- ``replace_device`` — atomarer Pool-Reassign-Tausch (alt retiren +
  neu zuweisen + DEVICE_REPLACED-Audit in einer Transaktion).
- ``retire_device`` — Stilllegung ohne Ersatz (DEVICE_RETIRED-Audit).

Race-Safety bei ``replace_device``: der UPDATE-Statement-WHERE-Block
(``heating_zone_id IS NULL AND retired_at IS NULL``) ist die echte
Wachposten-Stelle gegen parallele Hotelier-Sessions. Postgres-Default-
Isolation READ COMMITTED kann zwei Sessions denselben Pool-Device-Row
lesen lassen — der erste schreibt, der zweite findet bei seinem UPDATE
keine matching Row mehr (rowcount=0) und wird abgelehnt.

Begruendung CLAUDE.md §5.58: verstreute Device-Queries mit unsicherem
Lifecycle-Filter sind S4-Verstoss-Kandidaten (doppelte Downlinks
waehrend Tausch-Race).

Helper liefert lifecycle-aktive Devices. Health-Filter (``healthy``)
und Room-Scope sind Caller-Verantwortung — siehe
``engine_tasks._get_devices_for_zone``, das ``health_state ==
'healthy'`` zusaetzlich filtert.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.services.business_audit_service import record_business_action


class DeviceNotFound(LookupError):  # noqa: N818 — Brief-Signatur, AE-57-konvention
    """Device-ID existiert nicht in der DB."""


class DeviceStateError(ValueError):
    """Device befindet sich in einem fuer die Operation unzulaessigen Zustand
    (z.B. bereits retired, oder beim Tausch nicht aktiv-zugewiesen)."""


class PoolDeviceUnavailable(ValueError):  # noqa: N818 — Brief-Signatur, AE-57-konvention
    """Das angegebene neue Pool-Device ist nicht im Pool (heating_zone_id
    nicht NULL, retired_at gesetzt, oder vom parallelen Tausch bereits
    zugewiesen). Race-Schutz im UPDATE liefert dieselbe Exception bei
    DB-Rowcount=0."""


async def get_active_devices_for_zone(session: AsyncSession, zone_id: int) -> list[Device]:
    """Liefert aktive Devices einer HeatingZone (sortiert nach ``id`` ASC).

    Filter: ``heating_zone_id == zone_id AND retired_at IS NULL``.

    :param session: Async-Session, nicht committed durch diese Funktion.
    :param zone_id: Ziel-Zone-ID.
    :return: Liste von Device-Rows (kann leer sein).
    """
    stmt = (
        select(Device)
        .where(Device.heating_zone_id == zone_id)
        .where(Device.retired_at.is_(None))
        .order_by(Device.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_pool_devices(session: AsyncSession) -> list[Device]:
    """Liefert alle aktiven Pool-Devices (Reserve-Vickis).

    Filter: ``heating_zone_id IS NULL AND retired_at IS NULL``.
    Sortierung: ``created_at DESC`` (neueste zuerst — beim Tausch sieht
    Hotelier zuerst die juengst eingepairten Reserve-Geraete).

    :param session: Async-Session, nicht committed durch diese Funktion.
    :return: Liste von Pool-Device-Rows.
    """
    stmt = (
        select(Device)
        .where(Device.heating_zone_id.is_(None))
        .where(Device.retired_at.is_(None))
        .order_by(Device.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def replace_device(
    session: AsyncSession,
    *,
    old_device_id: int,
    new_pool_device_id: int,
    user_id: int | None = None,
) -> Device:
    """Atomarer Pool-Reassign-Tausch (AE-57 Entscheidung 6).

    Setzt in EINER Transaktion:
    - ``old.retired_at = now()``, ``old.retired_reason = "replaced_by_pool"``,
      ``old.replaced_by_device_id = new.id``
    - ``new.heating_zone_id = old.heating_zone_id``
    - ``BusinessAudit DEVICE_REPLACED`` mit ``target_id = old.id``

    Gate-Stack:

    1. Existenz: beide Device-IDs existieren. ``DeviceNotFound`` sonst.
    2. Konsistenz alt: ``old.retired_at IS NULL`` (noch aktiv) und
       ``old.heating_zone_id IS NOT NULL`` (Zone-gebunden, kein Pool-
       Tausch eines Pool-Devices). ``DeviceStateError`` sonst.
    3. Selbst-Tausch-Block: ``old_id != new_id``. ``ValueError`` sonst.
    4. Pool-Reservierung (race-safe): UPDATE auf ``new`` mit WHERE-
       Clause ``heating_zone_id IS NULL AND retired_at IS NULL``.
       ``rowcount != 1`` -> ``PoolDeviceUnavailable``. Echter Wachposten
       gegen Concurrent Writes (READ COMMITTED — Pre-Gate-Read kann
       stale sein).

    Caller committed die Transaktion. Falls Gate-Stack failed, Caller
    sollte rollback machen.
    """
    if old_device_id == new_pool_device_id:
        raise ValueError("Selbst-Tausch nicht erlaubt (old_id == new_id).")

    # Gate 1: Existenz alt
    old = await session.get(Device, old_device_id)
    if old is None:
        raise DeviceNotFound(f"old_device_id={old_device_id} nicht gefunden")

    # Gate 2: Konsistenz alt
    if old.retired_at is not None:
        raise DeviceStateError(
            f"old_device_id={old_device_id} ist bereits retired "
            f"({old.retired_at.isoformat()}); Re-Replace nicht erlaubt."
        )
    old_heating_zone_id = old.heating_zone_id
    if old_heating_zone_id is None:
        raise DeviceStateError(
            f"old_device_id={old_device_id} ist nicht zugewiesen "
            f"(heating_zone_id IS NULL); Tausch nur fuer aktiv-zugewiesene Devices."
        )

    # Gate 1b: Existenz neu (Pool-Pre-Check liefert klare Fehlermeldung
    # vor dem race-safe UPDATE).
    new = await session.get(Device, new_pool_device_id)
    if new is None:
        raise DeviceNotFound(f"new_pool_device_id={new_pool_device_id} nicht gefunden")

    # Gate 3: Pool-Pre-Check (klare Fehlermeldung; echter Wachposten ist
    # der UPDATE-Rowcount-Check unten).
    if new.heating_zone_id is not None or new.retired_at is not None:
        raise PoolDeviceUnavailable(
            f"new_pool_device_id={new_pool_device_id} ist nicht im Pool "
            f"(heating_zone_id={new.heating_zone_id!r}, "
            f"retired_at={new.retired_at!r})."
        )

    now = datetime.now(tz=UTC)

    # Gate 4: race-safe Pool-Reservierung. UPDATE-WHERE matched nur, wenn
    # das Device WIRKLICH noch im Pool ist (Concurrent Replace haette die
    # Zelle schon belegt → rowcount=0).
    reserve_stmt = (
        update(Device)
        .where(Device.id == new_pool_device_id)
        .where(Device.heating_zone_id.is_(None))
        .where(Device.retired_at.is_(None))
        .values(heating_zone_id=old_heating_zone_id)
        .returning(Device.id)
    )
    reserve_result = await session.execute(reserve_stmt)
    if len(reserve_result.fetchall()) != 1:
        raise PoolDeviceUnavailable(
            f"new_pool_device_id={new_pool_device_id} wurde parallel "
            f"vergeben (race-Schutz: UPDATE-Rowcount=0)."
        )

    # Gate 5: alten Device-Row retiren (Cross-Reference + Zone-Detach).
    old.retired_at = now
    old.retired_reason = "replaced_by_pool"
    old.replaced_by_device_id = new_pool_device_id
    old.heating_zone_id = None
    await session.flush()

    # Gate 6: BusinessAudit-Eintrag (atomar mit den UPDATEs).
    await record_business_action(
        session,
        user_id=user_id,
        action="DEVICE_REPLACED",
        target_type="device",
        target_id=old_device_id,
        old_value={
            "heating_zone_id": old_heating_zone_id,
            "retired_at": None,
        },
        new_value={
            "new_device_id": new_pool_device_id,
            "heating_zone_id": old_heating_zone_id,
            "replaced_at_iso": now.isoformat(),
        },
    )
    await session.refresh(old)
    return old


async def retire_device(
    session: AsyncSession,
    *,
    device_id: int,
    reason: str,
    user_id: int | None = None,
) -> Device:
    """Stilllegung ohne Ersatz (AE-57 Entscheidung 6 / DEVICE_RETIRED).

    Setzt ``retired_at = now()`` und ``retired_reason = reason``.
    ``heating_zone_id`` BLEIBT — ist Historie-Anker fuer ``sensor_reading``-
    FK und wird nicht geloescht (Sprint 13a AE-57 Konsequenz).

    Gate-Stack:

    1. Existenz: ``device_id`` existiert. ``DeviceNotFound`` sonst.
    2. Konsistenz: ``device.retired_at IS NULL``. ``DeviceStateError``
       sonst (Re-Retire nicht erlaubt — unwiderruflich).

    Caller committed die Transaktion.
    """
    device = await session.get(Device, device_id)
    if device is None:
        raise DeviceNotFound(f"device_id={device_id} nicht gefunden")
    if device.retired_at is not None:
        raise DeviceStateError(
            f"device_id={device_id} ist bereits retired ({device.retired_at.isoformat()})."
        )

    now = datetime.now(tz=UTC)
    device.retired_at = now
    device.retired_reason = reason
    await session.flush()

    await record_business_action(
        session,
        user_id=user_id,
        action="DEVICE_RETIRED",
        target_type="device",
        target_id=device_id,
        old_value=None,
        new_value={
            "reason": reason,
            "retired_at_iso": now.isoformat(),
            "heating_zone_id": device.heating_zone_id,
        },
    )
    await session.refresh(device)
    return device
