"""Pairing-Service: legt Device-Row + DEVICE_PAIRED-Audit + OW-Downlink an (Sprint 13a T4).

Konsumiert ``PairingCsvRow`` (T2) + Pre-Flight-Validierung (T3).
``pair_batch`` iteriert mit Pro-Row-Savepoint (``session.begin_nested()``)
— ein Fehler in einer Row rollback nur den Savepoint, andere Rows
bleiben unangetastet. Top-Level-``commit()`` ist Caller-Aufgabe (CLI
T6), damit Tests die Session am Ende sauber rollback koennen
(analog ``test_override_pms_hook`` Pattern).

``app_key`` aus der CSV wird **nicht** in der heizung-DB persistiert.
Der AppKey gehoert zur ChirpStack-Registrierung (Hotelier macht das
manuell vor September via ChirpStack-Web-UI-Bulk-Import) — heizung-DB
kennt nur ``dev_eui`` als Identifier-Schluessel. Die CSV-Spalte
``app_key`` ist informational fuer den Hotelier zum Cross-Reference
mit der ChirpStack-UI.

Gate-Stack-Reihenfolge (§S5 Defensive bei externen Quellen):

1. ``DEV_EUI_EXISTS``: Pre-Check, kein Audit, kein Downlink (skipped).
2. ``ZONE_NOT_FOUND``: Defensive — Pre-Flight ``validate_against_db``
   (T3) sollte das schon abfangen. Hier nur Sicherheitsnetz.
3. Device-Row anlegen + flush.
4. ``DEVICE_PAIRED``-BusinessAudit in derselben Transaktion.
5. Open-Window-Detection-Downlink (``0x4501020F``-aequivalent via
   ``set_open_window_detection`` AE-48). Bei Downlink-Failure bleibt
   die Device-Row erhalten (kein Rollback), Status ``error`` — der
   Downlink kann via Eingangstest (T5) oder manueller Re-Send
   wiederholt werden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.services.business_audit_service import record_business_action
from heizung.services.downlink_adapter import set_open_window_detection

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.scripts.pairing.csv_row import PairingCsvRow

logger = logging.getLogger(__name__)

# Open-Window-Detection-Defaults aus AE-47-Vendor-Konvention
# (identisch zu ``scripts/activate_open_window_detection.py``).
OW_DEFAULT_ENABLED: bool = True
OW_DEFAULT_DURATION_MIN: int = 10
OW_DEFAULT_DELTA_C: Decimal = Decimal("1.5")

# Vicki-Hardware-Identifikation. Heute pairen wir ausschliesslich
# MClimate-Vickis (Thermostat). Andere Vendoren / Sensor-Devices
# laufen ueber eigenen Pfad, nicht ueber diesen CSV-Import.
DEVICE_MODEL_VICKI: str = "Vicki"


PairStatus = Literal["paired", "skipped_exists", "error"]


@dataclass(frozen=True, slots=True)
class PairResult:
    """Ein Pairing-Ergebnis pro CSV-Row.

    ``status``:
    - ``paired``: Device-Row angelegt, Audit geschrieben, Downlink OK.
    - ``skipped_exists``: DevEUI existiert bereits in DB, kein Side-Effekt.
    - ``error``: Pairing fehlgeschlagen oder Downlink failed. Bei
      Downlink-Failure ist das Device dennoch in DB (``device_id``
      gesetzt).
    """

    status: PairStatus
    dev_eui: str
    row_number: int
    is_pool: bool
    device_id: int | None = None
    error_msg: str | None = None


async def _lookup_zone(session: AsyncSession, zimmer_nummer: int, zone_label: str) -> int | None:
    """Aufloesung ``(zimmer_nummer, zone_label) -> heating_zone.id``.

    Identische Lookup-Logik wie ``validate_against_db`` aus T3
    (``Room.number == str(...)`` + ``HeatingZone.name == ...``).
    """
    stmt = (
        select(HeatingZone.id)
        .join(Room, Room.id == HeatingZone.room_id)
        .where(Room.number == str(zimmer_nummer))
        .where(HeatingZone.name == zone_label)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def pair_device(
    row: PairingCsvRow,
    row_number: int,
    session: AsyncSession,
    *,
    user_id: int | None = None,
) -> PairResult:
    """Pairt ein einzelnes Geraet: Device-Row + Audit + OW-Downlink.

    Caller ist fuer ``session.commit()`` zustaendig (vgl. override_service-
    Pattern). Diese Funktion macht nur ``flush()``, damit ``device.id``
    fuer Audit + Logger verfuegbar ist.

    Downlink-Fehler werden hier gefangen und in ``PairResult(status=
    "error")`` konvertiert — der Device-Row bleibt erhalten, damit
    ein nachgelagerter Eingangstest (T5) oder manueller Re-Send den
    Downlink wiederholen kann.

    :param row: validierte Pydantic-Row aus T2/T3.
    :param row_number: 1-basierter CSV-Zeilen-Offset (Zeile 1 = Header,
        Zeile 2 = erste Daten-Row). Geht ins Audit als
        ``csv_row_number``.
    :param session: ``AsyncSession``. Nicht committed durch diese
        Funktion.
    :param user_id: BusinessAudit-``user_id``. ``None`` = System-
        Trigger (Praezedenzfall siehe Sprint-13-Hygiene
        ``OVERRIDES_AUTO_REVOKED_ON_CHECKOUT``).
    """
    # Gate 1: DevEUI-Existenz.
    existing_stmt = select(Device.id).where(Device.dev_eui == row.dev_eui)
    existing_id = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing_id is not None:
        logger.info(
            "pair_device skipped: dev_eui=%s existiert bereits (device_id=%s)",
            row.dev_eui,
            existing_id,
        )
        return PairResult(
            status="skipped_exists",
            dev_eui=row.dev_eui,
            row_number=row_number,
            is_pool=row.is_pool_device,
            device_id=existing_id,
            error_msg=(
                "DEV_EUI_EXISTS: Re-Pair via Sprint 13b Tausch-Workflow "
                "(retired_at + replaced_by_device_id)."
            ),
        )

    # Gate 2: Zone-Lookup falls Active-Row.
    heating_zone_id: int | None = None
    if not row.is_pool_device:
        # ``is_pool_device == False`` impliziert zimmer_nummer + zone_label
        # gesetzt (T2 model_validator garantiert das).
        assert row.zimmer_nummer is not None
        assert row.zone_label is not None
        heating_zone_id = await _lookup_zone(session, row.zimmer_nummer, row.zone_label)
        if heating_zone_id is None:
            # Defensive: validate_against_db (T3) sollte das vorher gefangen
            # haben. Falls doch nicht: hart abbrechen ohne Device-Anlage.
            return PairResult(
                status="error",
                dev_eui=row.dev_eui,
                row_number=row_number,
                is_pool=row.is_pool_device,
                error_msg=(
                    f"ZONE_NOT_FOUND: Zimmer {row.zimmer_nummer} / Zone "
                    f"'{row.zone_label}' nicht in DB. "
                    "Phase-0-Drift — validate_against_db haette das fangen muessen."
                ),
            )

    # Gate 3: Device-Row anlegen.
    device = Device(
        dev_eui=row.dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model=DEVICE_MODEL_VICKI,
        heating_zone_id=heating_zone_id,
    )
    session.add(device)
    await session.flush()
    assert device.id is not None  # flush hat PK gesetzt

    # Gate 4: BusinessAudit (atomar mit Device-Insert, Caller committet).
    await record_business_action(
        session,
        user_id=user_id,
        action="DEVICE_PAIRED",
        target_type="device",
        target_id=device.id,
        old_value=None,
        new_value={
            "dev_eui": row.dev_eui,
            "heating_zone_id": heating_zone_id,
            "is_pool": row.is_pool_device,
            "csv_row_number": row_number,
        },
    )

    # Gate 5: Open-Window-Detection-Downlink (AE-48).
    # Pool-Geraete bekommen ebenfalls den OW-Downlink — Reserve soll
    # ab Werkseinstellung funktionsbereit sein wenn spaeter zugewiesen.
    try:
        await set_open_window_detection(
            row.dev_eui,
            enabled=OW_DEFAULT_ENABLED,
            duration_min=OW_DEFAULT_DURATION_MIN,
            delta_c=OW_DEFAULT_DELTA_C,
        )
    except Exception as exc:  # noqa: BLE001 — Downlink-Failure ist Soft-Fail
        # Device-Row + Audit bleiben in DB. Downlink kann via Eingangstest
        # (T5) oder manuellem Re-Send wiederholt werden. Re-Run des CSV-
        # Imports trifft Gate 1 (skipped_exists), kein Doppel-Insert.
        logger.warning(
            "pair_device: OW-Downlink failed dev_eui=%s device_id=%s exc=%s",
            row.dev_eui,
            device.id,
            exc,
        )
        return PairResult(
            status="error",
            dev_eui=row.dev_eui,
            row_number=row_number,
            is_pool=row.is_pool_device,
            device_id=device.id,
            error_msg=f"DOWNLINK_FAILED: {type(exc).__name__}: {exc}",
        )

    logger.info(
        "pair_device ok: dev_eui=%s device_id=%s heating_zone_id=%s is_pool=%s",
        row.dev_eui,
        device.id,
        heating_zone_id,
        row.is_pool_device,
    )
    return PairResult(
        status="paired",
        dev_eui=row.dev_eui,
        row_number=row_number,
        is_pool=row.is_pool_device,
        device_id=device.id,
    )


async def pair_batch(
    rows: list[PairingCsvRow],
    session: AsyncSession,
    *,
    user_id: int | None = None,
) -> list[PairResult]:
    """Iteriert ueber alle Rows mit Pro-Row-Savepoint-Isolation.

    Pro Row ``session.begin_nested()``-Savepoint. Bei sauberem Durchlauf
    (auch bei Downlink-Failure mit ``PairResult.status="error"`` und
    erhaltenem Device-Row) wird der Savepoint committed. Bei
    unerwarteter Exception (z.B. DB-Connection-Drop, Schema-Verstoss)
    wird der Savepoint rollback und ein Error-Result eingehaengt;
    nachfolgende Rows werden trotzdem versucht.

    Top-Level-``commit()`` ist Caller-Aufgabe (CLI T6) — diese Funktion
    flusht nur, damit Tests die Session am Ende sauber rollback koennen
    (analog ``test_override_pms_hook``).

    :param rows: Liste validierter Rows aus T3 ``parse_csv``.
    :param session: ``AsyncSession``. Pro Row Savepoint, kein
        Top-Level-Commit.
    :param user_id: weitergereicht an ``pair_device``.
    :return: ``PairResult``-Liste in Input-Reihenfolge (gleicher
        ``row_number``-Offset).
    """
    results: list[PairResult] = []
    for offset, row in enumerate(rows, start=2):
        savepoint = await session.begin_nested()
        try:
            result = await pair_device(row, offset, session, user_id=user_id)
            await savepoint.commit()
        except Exception as exc:  # noqa: BLE001 — pair_batch ist Top-Level-Wrapper
            await savepoint.rollback()
            logger.exception(
                "pair_batch: unerwarteter Fehler bei row %s dev_eui=%s",
                offset,
                row.dev_eui,
            )
            result = PairResult(
                status="error",
                dev_eui=row.dev_eui,
                row_number=offset,
                is_pool=row.is_pool_device,
                error_msg=f"UNEXPECTED: {type(exc).__name__}: {exc}",
            )
        results.append(result)
    return results
