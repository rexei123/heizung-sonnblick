"""Pairing-Service: legt Device-Row + DEVICE_PAIRED-Audit an (Sprint 13a T4).

Konsumiert ``PairingCsvRow`` (T2) + Pre-Flight-Validierung (T3).
``pair_batch`` iteriert mit Pro-Row-Savepoint (``session.begin_nested()``)
— ein Fehler in einer Row rollback nur den Savepoint, andere Rows
bleiben unangetastet. Top-Level-``commit()`` ist Caller-Aufgabe (CLI
T6), damit Tests die Session am Ende sauber rollback koennen
(analog ``test_override_pms_hook`` Pattern).

``app_key`` aus der CSV wird **nicht** in der heizung-DB persistiert.
Der AppKey gehoert zur ChirpStack-Registrierung (Sprint 17 / C1:
``infra/chirpstack/provision_devices.py``) — heizung-DB kennt nur
``dev_eui`` als Identifier-Schluessel. Die CSV-Spalte ``app_key`` ist
Eingabe fuer das Provisioning-Skript und Cross-Reference fuer den
Hotelier.

Sprint 17 (Entscheidung E3, Task C3): **Der Pairing-Lauf sendet keinen
Downlink mehr.** Bis Sprint 16 schickte Gate 5 hier einen
Open-Window-Detection-Downlink (``0x45``) an jedes frisch gepairte
Geraet. Das war aus drei Gruenden falsch:

1. **Kein FW-Gate.** ``set_open_window_detection`` kodiert die
   0x45-Variante, die erst ab FW >= 4.2 existiert. Der Pairing-Lauf
   kennt die Firmware des Geraets zu diesem Zeitpunkt nicht — bei drei
   Produktionschargen ging der Befehl blind raus (B-9.11x.b-2).
2. **S4 (Hardware-Schutz).** Ein CSV-Import ist ein Datenbank-Vorgang.
   Dass er als Seiteneffekt ~104 Funkbefehle an produktive Hardware
   ausloest — im ``--dry-run`` sogar dann, wenn die DB-Aenderung
   verworfen wird — ist ein Befehlspfad ohne Bestaetigungs-Strategie.
3. **Reihenfolge.** Die Open-Window-Detection gehoert nach der Montage
   gesetzt, nicht beim Tisch-Import.

Der OW-Rollout laeuft stattdessen ueber
``heizung.scripts.activate_open_window_detection`` — dasselbe Vendor-
Byte-Layout, aber mit FW-Query (0x04), Wartezeit und FW-Gate
(``MIN_FW_FOR_OW_SET``). RUNBOOK §10h beschreibt die Reihenfolge.

Gate-Stack-Reihenfolge (§S5 Defensive bei externen Quellen):

1. Geraet existiert bereits -> ``_handle_existing``: leere Metadaten-
   Felder befuellen (``enriched``), abweichende melden (``conflict``),
   nichts zu tun (``skipped_exists``). Zone bleibt unangetastet.
2. ``ZONE_NOT_FOUND``: Defensive — Pre-Flight ``validate_against_db``
   (T3) sollte das schon abfangen. Hier nur Sicherheitsnetz.
3. Device-Row anlegen + flush, inkl. der optionalen Metadaten.
4. ``DEVICE_PAIRED``-BusinessAudit in derselben Transaktion.

Sprint 17 (E4/C2) — Metadaten-Anreicherung
------------------------------------------

Die CSV bringt optional ``hardware_nummer``, ``app_eui`` und
``serial_number`` mit (Abbildung siehe ``csv_row``-Docstring). Fuer neue
Geraete wandern sie direkt in die Device-Row. Fuer **bestehende** Geraete
gilt: nachtragen, nie korrigieren. Leere Felder werden befuellt,
abweichende Werte bleiben stehen und werden als Konflikt gemeldet.

Das ist der Fall der vier Testgeraete: sie stehen seit Sprint 6 in der DB,
haben aber weder AppEUI noch Seriennummer. Aus derselben CSV, aus der die
100 neuen Geraete kommen, holen sie sich die fehlenden Werte — ohne dass
ihr gewachsenes ``label`` stillschweigend ueberschrieben wird.

Der Lauf ist damit rein transaktional: entweder Device-Row + Audit
stehen, oder die Row ist nicht angelegt. Kein Teil-Zustand aus einem
fehlgeschlagenen Funkbefehl mehr (B-Sprint13a-5 ist damit gegenstandslos
— es gibt keinen ``pending_ow_resend``-Zustand, den man markieren
muesste).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.services.business_audit_service import record_business_action

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.scripts.pairing.csv_row import PairingCsvRow

logger = logging.getLogger(__name__)

# Vicki-Hardware-Identifikation. Heute pairen wir ausschliesslich
# MClimate-Vickis (Thermostat). Andere Vendoren / Sensor-Devices
# laufen ueber eigenen Pfad, nicht ueber diesen CSV-Import.
DEVICE_MODEL_VICKI: str = "Vicki"

# Sprint 17 (E4/C2): Abbildung CSV-Spalte -> Device-Spalte fuer die drei
# optionalen Metadaten. Begruendung der Zuordnung steht im Modul-Docstring
# von ``csv_row`` (AE-61 fuer hardware_number, D5 fuer label).
METADATA_MAP: dict[str, str] = {
    "hardware_nummer": "label",
    "app_eui": "app_eui",
    "serial_number": "hardware_number",
}


PairStatus = Literal["paired", "enriched", "skipped_exists", "conflict", "error"]


@dataclass(frozen=True, slots=True)
class PairResult:
    """Ein Pairing-Ergebnis pro CSV-Row.

    ``status``:
    - ``paired``: Device-Row neu angelegt, Audit geschrieben.
    - ``enriched``: Geraet existierte, mindestens ein leeres Metadaten-Feld
      wurde aus der CSV befuellt (Sprint 17 / E4).
    - ``skipped_exists``: Geraet existierte, nichts zu befuellen, kein
      Widerspruch — echter No-op.
    - ``conflict``: Geraet existierte und die CSV nennt fuer mindestens ein
      Feld einen **anderen**, nicht-leeren Wert. Der Bestand wird **nicht**
      ueberschrieben; leere Felder derselben Zeile werden trotzdem befuellt.
    - ``error``: Pairing fehlgeschlagen. Seit Sprint 17 (C3) gibt es
      keinen Downlink-Pfad mehr, der eine Device-Row zuruecklaesst —
      ``error`` bedeutet ausnahmslos: **keine** Device-Row angelegt
      (``device_id is None``).

    ``filled`` und ``conflicts`` sind nur bei ``enriched``/``conflict``/
    ``skipped_exists`` gefuellt und tragen die betroffenen **Device**-
    Spaltennamen.
    """

    status: PairStatus
    dev_eui: str
    row_number: int
    is_pool: bool
    device_id: int | None = None
    error_msg: str | None = None
    filled: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def _csv_metadata(row: PairingCsvRow) -> dict[str, str]:
    """Gesetzte Metadaten der Zeile als ``device``-Spalte -> Wert.

    ``None``-Werte (Spalte fehlt oder Zelle leer) fallen raus — eine nicht
    erfasste Angabe darf einen Bestandswert weder ueberschreiben noch als
    Konflikt gelten.
    """
    out: dict[str, str] = {}
    for csv_field, device_attr in METADATA_MAP.items():
        value = getattr(row, csv_field)
        if value is not None:
            out[device_attr] = value
    return out


def _reconcile_metadata(device: Device, row: PairingCsvRow) -> tuple[list[str], list[str]]:
    """Gleicht die CSV-Metadaten gegen ein **bestehendes** Geraet ab.

    Regel (Sprint 17 / E4): leere Bestandsfelder werden befuellt,
    abweichende Werte werden **nicht** ueberschrieben, sondern gemeldet.
    Der Import ist damit nachtragend, nie korrigierend — eine Korrektur
    ist ein bewusster Einzelakt ueber ``PATCH /api/v1/devices/{id}``.

    Mutiert ``device`` fuer die befuellbaren Felder (Caller flusht/committet).

    :return: ``(befuellte Spalten, widerspruechliche Spalten)``, beide
        sortiert fuer deterministische Ausgabe.
    """
    filled: list[str] = []
    conflicts: list[str] = []
    for device_attr, csv_value in _csv_metadata(row).items():
        current = getattr(device, device_attr)
        if current is None or current == "":
            setattr(device, device_attr, csv_value)
            filled.append(device_attr)
        elif current != csv_value:
            conflicts.append(device_attr)
    return sorted(filled), sorted(conflicts)


async def _lookup_zone(session: AsyncSession, zimmer_nummer: str, zone_label: str) -> int | None:
    """Aufloesung ``(zimmer_nummer, zone_label) -> heating_zone.id``.

    Identische Lookup-Logik wie ``validate_against_db`` aus T3
    (``Room.number == ...`` + ``HeatingZone.name == ...``).
    """
    stmt = (
        select(HeatingZone.id)
        .join(Room, Room.id == HeatingZone.room_id)
        .where(Room.number == zimmer_nummer)
        .where(HeatingZone.name == zone_label)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _handle_existing(
    device: Device,
    row: PairingCsvRow,
    row_number: int,
    session: AsyncSession,
    *,
    user_id: int | None,
) -> PairResult:
    """Gate 1b (Sprint 17 / E4): Geraet existiert — anreichern statt abweisen.

    Die Zone-Zuordnung bleibt **unangetastet**. Ein bereits gepairtes Geraet
    umzuhaengen ist Aufgabe von ``assign`` bzw. des Tausch-Endpoints, nicht
    des Imports — sonst wuerde ein versehentlich zweimal eingelesenes CSV
    stillschweigend Zonen verschieben (S2/S4).
    """
    filled, conflicts = _reconcile_metadata(device, row)

    if filled:
        await session.flush()
        await record_business_action(
            session,
            user_id=user_id,
            action="DEVICE_METADATA_ENRICHED",
            target_type="device",
            target_id=device.id,
            old_value=None,
            new_value={
                "dev_eui": row.dev_eui,
                "filled_fields": filled,
                "conflicting_fields": conflicts,
                "csv_row_number": row_number,
            },
        )

    if conflicts:
        details = ", ".join(
            f"{attr}: DB={getattr(device, attr)!r} != CSV={_csv_metadata(row)[attr]!r}"
            for attr in conflicts
        )
        msg = (
            f"METADATA_CONFLICT: {details}. Bestand NICHT ueberschrieben — "
            "Korrektur bewusst via PATCH /api/v1/devices/{id}."
        )
        if filled:
            msg += f" Befuellt wurden: {', '.join(filled)}."
        logger.warning("pair_device conflict: dev_eui=%s %s", row.dev_eui, details)
        return PairResult(
            status="conflict",
            dev_eui=row.dev_eui,
            row_number=row_number,
            is_pool=row.is_pool_device,
            device_id=device.id,
            error_msg=msg,
            filled=tuple(filled),
            conflicts=tuple(conflicts),
        )

    if filled:
        logger.info(
            "pair_device enriched: dev_eui=%s device_id=%s felder=%s",
            row.dev_eui,
            device.id,
            filled,
        )
        return PairResult(
            status="enriched",
            dev_eui=row.dev_eui,
            row_number=row_number,
            is_pool=row.is_pool_device,
            device_id=device.id,
            filled=tuple(filled),
        )

    logger.info(
        "pair_device skipped: dev_eui=%s existiert bereits (device_id=%s), nichts zu ergaenzen",
        row.dev_eui,
        device.id,
    )
    return PairResult(
        status="skipped_exists",
        dev_eui=row.dev_eui,
        row_number=row_number,
        is_pool=row.is_pool_device,
        device_id=device.id,
        error_msg=(
            "DEV_EUI_EXISTS: keine neuen Metadaten. Re-Pair nach Werksreset "
            "laeuft ueber den Sprint-13b-Tausch-Workflow."
        ),
    )


async def pair_device(
    row: PairingCsvRow,
    row_number: int,
    session: AsyncSession,
    *,
    user_id: int | None = None,
) -> PairResult:
    """Pairt ein einzelnes Geraet: Device-Row + Audit.

    Caller ist fuer ``session.commit()`` zustaendig (vgl. override_service-
    Pattern). Diese Funktion macht nur ``flush()``, damit ``device.id``
    fuer Audit + Logger verfuegbar ist.

    Sprint 17 (C3): kein Downlink mehr. Die Funktion beruehrt
    ausschliesslich die Datenbank.

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
    # Gate 1: DevEUI-Existenz (bewusst OHNE retired_at-Filter, Sprint
    # 13b.1, AE-57). Pre-Flight-Disziplin: CSV-Bulk-Pairing rejected auch
    # retired Devices mit identischer DevEUI. Re-Pair nach Werksreset
    # geht ueber Tausch-Endpoint (DEVICE_REPLACED), nicht CSV.
    existing_stmt = select(Device).where(Device.dev_eui == row.dev_eui)
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing is not None:
        return await _handle_existing(existing, row, row_number, session, user_id=user_id)

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

    # Gate 3: Device-Row anlegen, inkl. der optionalen Metadaten (E4/C2).
    metadata = _csv_metadata(row)
    device = Device(
        dev_eui=row.dev_eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model=DEVICE_MODEL_VICKI,
        heating_zone_id=heating_zone_id,
        **metadata,
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
            # Welche Metadaten der Import mitgebracht hat — leere Spalten
            # erscheinen nicht, damit "nicht erfasst" und "leer gesetzt"
            # im Audit unterscheidbar bleiben.
            "metadata": metadata,
        },
    )

    logger.info(
        "pair_device ok: dev_eui=%s device_id=%s heating_zone_id=%s is_pool=%s metadata=%s",
        row.dev_eui,
        device.id,
        heating_zone_id,
        row.is_pool_device,
        sorted(metadata),
    )
    return PairResult(
        status="paired",
        dev_eui=row.dev_eui,
        row_number=row_number,
        is_pool=row.is_pool_device,
        device_id=device.id,
        filled=tuple(sorted(metadata)),
    )


async def pair_batch(
    rows: list[PairingCsvRow],
    session: AsyncSession,
    *,
    user_id: int | None = None,
) -> list[PairResult]:
    """Iteriert ueber alle Rows mit Pro-Row-Savepoint-Isolation.

    Pro Row ``session.begin_nested()``-Savepoint. Bei sauberem Durchlauf
    wird der Savepoint committed. Bei unerwarteter Exception (z.B.
    DB-Connection-Drop, Schema-Verstoss) wird der Savepoint rollback und
    ein Error-Result eingehaengt; nachfolgende Rows werden trotzdem
    versucht.

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
