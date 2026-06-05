r"""CLI-Entrypoint fuer den Zimmer-Stammdaten-Seed (Weg A, Mapping auf Bestand).

Aufruf via ``python -m heizung.scripts.seed_rooms <subcommand> [csv]``.

Ersetzt die fiktiven Test-Zimmer durch die echte Zimmerliste (45 Zimmer /
103 Zonen) aus ``Zimmerliste_seed.csv``. **Reiner Stammdaten-Seed** — kein
device-Bezug, kein MQTT-Downlink, keine Migration, kein Enum-Touch, keine
neue Spalte.

Mapping CSV -> Bestandsschema (develop):

- Zimmer (``room``):
    Zimmer_Nummer    -> room.number
    Anzeigename      -> room.display_name
    Etage            -> room.floor
    Ausrichtung      -> room.orientation  (N/S/O/W -> Orientation-Enum, O=EAST)
    Zimmer_Kategorie -> room.room_type_id (FK auf RoomType "Doppelzimmer"/"Suite")
    room.status               = RoomStatus.VACANT
    room.guest_override_blocked = False
    room.notes                = None
    PMS_Mapping: ignoriert (== Zimmernummer, kein Konsument, kein Feld)
- Zone (``heating_zone``):
    Zone_Label -> heating_zone.name
    Room_Type  -> heating_zone.kind:  Schlafzimmer -> bedroom,
                  Badezimmer -> bathroom, Kinderzimmer -> bedroom
                  ("Kinderzimmer" bleibt nur in heating_zone.name erhalten)

Subcommands:

- ``validate [csv]``  Schema-Pruefung der CSV (kein Side-Effekt, keine DB).
- ``import [csv]``    Wipe + Reseed in EINER Transaktion. ``--dry-run``
                       rollbackt die DB-Aenderungen. Blockierende Vorstufe:
                       bricht ab, wenn an bestehenden heating_zone-Eintraegen
                       Devices haengen (kein stiller Vicki-Orphan).

``csv`` ist optional — ohne Argument wird die eingebettete Package-Data
``heizung/scripts/seed_data/Zimmerliste_seed.csv`` genutzt (Lauf ohne scp).

Aufruf-Beispiele:

    python -m heizung.scripts.seed_rooms validate
    python -m heizung.scripts.seed_rooms validate /tmp/Zimmerliste_seed.csv
    python -m heizung.scripts.seed_rooms import --dry-run
    python -m heizung.scripts.seed_rooms import

Auf heizung-test/heizung-main via Docker (Container-Name nicht hart annehmen,
Prod-Pattern ``deploy-api-1``):

    docker exec <api-container> python -m heizung.scripts.seed_rooms validate
    docker exec <api-container> python -m heizung.scripts.seed_rooms import --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv as csv_module
import importlib.resources
import io
import logging
import os
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

# App-Settings ladbar machen (Pattern aus pair_devices.py).
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung",
)

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.enums import HeatingZoneKind, Orientation, RoomStatus  # noqa: E402
from heizung.models.heating_zone import HeatingZone  # noqa: E402
from heizung.models.room import Room  # noqa: E402
from heizung.models.room_type import RoomType  # noqa: E402

logger = logging.getLogger("seed_rooms")

# ---------------------------------------------------------------------------
# Konstanten / Mapping (Weg A)
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "Zimmer_Nummer",
    "Anzeigename",
    "Etage",
    "Ausrichtung",
    "Zimmer_Kategorie",
    "PMS_Mapping",
    "Zone_Index",
    "Zone_Label",
    "Room_Type",
]

# CSV-Ausrichtung (deutsch) -> Orientation-Enum. Insb. O (Ost) -> EAST ("E").
ORIENTATION_MAP: dict[str, Orientation] = {
    "N": Orientation.NORTH,
    "S": Orientation.SOUTH,
    "O": Orientation.EAST,
    "W": Orientation.WEST,
}

# CSV-Room_Type (Zonentyp) -> HeatingZoneKind. Kinderzimmer -> bedroom
# (KEIN neuer Enum-Wert); "Kinderzimmer" bleibt in heating_zone.name.
KIND_MAP: dict[str, HeatingZoneKind] = {
    "Schlafzimmer": HeatingZoneKind.BEDROOM,
    "Badezimmer": HeatingZoneKind.BATHROOM,
    "Kinderzimmer": HeatingZoneKind.BEDROOM,
}

ALLOWED_ROOM_TYPES = {"Doppelzimmer", "Suite"}

# Step-0-Defaults fuer fehlende RoomTypes (identisch zu seed.py:58-83).
# is_bookable ist fuer beide True; nur die Beschreibung variiert.
ROOM_TYPE_DEFAULTS: dict[str, str] = {
    "Doppelzimmer": "Standard-Zweibettzimmer mit Bad.",
    "Suite": "Größere Einheit mit getrenntem Wohnbereich.",
}
_DEFAULT_T_OCCUPIED = Decimal("21.0")
_DEFAULT_T_VACANT = Decimal("18.0")
_DEFAULT_T_NIGHT = Decimal("19.0")

EXPECTED_ROOMS = 45
EXPECTED_ZONES = 103
# Akzeptanzkriterium: Kinderzimmer-Zonen exakt an diesen Zimmern.
CHILD_ROOMS = {"107", "115", "207", "215", "302", "303", "306", "310", "401"}

EMBEDDED_CSV_PACKAGE = "heizung.scripts.seed_data"
EMBEDDED_CSV_NAME = "Zimmerliste_seed.csv"

_INT_RE = re.compile(r"-?\d+")
_FLOAT_INT_RE = re.compile(r"-?\d+\.0+")


# ---------------------------------------------------------------------------
# CSV-Parsing + Schema-Validierung (kein Side-Effekt, keine DB)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedRow:
    """Eine validierte + coercte CSV-Zeile (eine Zone)."""

    row_number: int
    zimmer_nummer: str
    anzeigename: str
    etage: int
    ausrichtung: str  # CSV-Buchstabe (N/S/O/W); Mapping bei Bau
    zimmer_kategorie: str
    zone_index: int
    zone_label: str
    room_type: str  # Schlafzimmer/Badezimmer/Kinderzimmer


def _coerce_int(value: str, field: str, row_no: int, errors: list[str]) -> int | None:
    """Int-Coercion inkl. ``"52.0" -> 52`` (B-Sprint13a-3)."""
    v = value.strip()
    if _INT_RE.fullmatch(v):
        return int(v)
    if _FLOAT_INT_RE.fullmatch(v):
        return int(float(v))
    errors.append(f"Zeile {row_no}: {field}='{value}' ist kein Integer")
    return None


def _read_csv_text(path: Path | None) -> str:
    """CSV-Text laden: expliziter Pfad oder eingebettete Package-Data."""
    if path is not None:
        return path.read_text(encoding="utf-8")
    resource = importlib.resources.files(EMBEDDED_CSV_PACKAGE) / EMBEDDED_CSV_NAME
    return resource.read_text(encoding="utf-8")


def parse_and_validate(text: str) -> tuple[list[SeedRow], list[str]]:
    """Parst CSV-Text und prueft das Schema. Reine Funktion (kein I/O, keine DB).

    Returns ``(rows, errors)``. Bei ``errors`` ist ``rows`` ggf. unvollstaendig
    (nur die fehlerfrei coercbaren Zeilen) — der Aufrufer bricht bei
    ``errors`` ab.
    """
    errors: list[str] = []
    reader = csv_module.DictReader(io.StringIO(text))

    if reader.fieldnames is None or list(reader.fieldnames) != CSV_COLUMNS:
        errors.append(
            f"Header-Mismatch. Erwartet {CSV_COLUMNS}, gefunden "
            f"{list(reader.fieldnames) if reader.fieldnames else None}"
        )
        return [], errors

    rows: list[SeedRow] = []
    for i, raw in enumerate(reader, start=2):  # Zeile 1 = Header
        etage = _coerce_int(raw["Etage"], "Etage", i, errors)
        zone_index = _coerce_int(raw["Zone_Index"], "Zone_Index", i, errors)
        nummer_int = _coerce_int(raw["Zimmer_Nummer"], "Zimmer_Nummer", i, errors)
        pms_int = _coerce_int(raw["PMS_Mapping"], "PMS_Mapping", i, errors)

        ausrichtung = raw["Ausrichtung"].strip()
        if ausrichtung not in ORIENTATION_MAP:
            errors.append(
                f"Zeile {i}: Ausrichtung='{ausrichtung}' nicht in {sorted(ORIENTATION_MAP)}"
            )
        room_type = raw["Room_Type"].strip()
        if room_type not in KIND_MAP:
            errors.append(f"Zeile {i}: Room_Type='{room_type}' nicht in {sorted(KIND_MAP)}")
        zimmer_kategorie = raw["Zimmer_Kategorie"].strip()
        if zimmer_kategorie not in ALLOWED_ROOM_TYPES:
            errors.append(
                f"Zeile {i}: Zimmer_Kategorie='{zimmer_kategorie}' nicht in "
                f"{sorted(ALLOWED_ROOM_TYPES)}"
            )
        # PMS-Konsistenz (Weg-A-Entscheidung: PMS == Zimmernummer).
        if nummer_int is not None and pms_int is not None and nummer_int != pms_int:
            errors.append(f"Zeile {i}: PMS_Mapping={pms_int} != Zimmer_Nummer={nummer_int}")

        if etage is None or zone_index is None or nummer_int is None:
            continue  # Coercion-Fehler bereits gesammelt
        rows.append(
            SeedRow(
                row_number=i,
                zimmer_nummer=str(nummer_int),
                anzeigename=raw["Anzeigename"].strip(),
                etage=etage,
                ausrichtung=ausrichtung,
                zimmer_kategorie=zimmer_kategorie,
                zone_index=zone_index,
                zone_label=raw["Zone_Label"].strip(),
                room_type=room_type,
            )
        )

    errors.extend(_cross_row_checks(rows))
    return rows, errors


def _cross_row_checks(rows: list[SeedRow]) -> list[str]:
    """Aggregat-Checks ueber alle Zeilen (Counts, je-Zimmer-Invarianten)."""
    errors: list[str] = []
    if len(rows) != EXPECTED_ZONES:
        errors.append(f"Zonen-Anzahl {len(rows)} != erwartet {EXPECTED_ZONES}")

    by_room: dict[str, list[SeedRow]] = {}
    for r in rows:
        by_room.setdefault(r.zimmer_nummer, []).append(r)

    if len(by_room) != EXPECTED_ROOMS:
        errors.append(f"Zimmer-Anzahl {len(by_room)} != erwartet {EXPECTED_ROOMS}")

    for number, zone_rows in by_room.items():
        # Zimmer-Attribute muessen ueber alle Zone-Zeilen konsistent sein.
        for attr in ("anzeigename", "etage", "ausrichtung", "zimmer_kategorie"):
            values = {getattr(z, attr) for z in zone_rows}
            if len(values) > 1:
                errors.append(f"Zimmer {number}: inkonsistente {attr}: {sorted(map(str, values))}")
        # Genau 1 Badezimmer pro Zimmer.
        baths = sum(1 for z in zone_rows if z.room_type == "Badezimmer")
        if baths != 1:
            errors.append(f"Zimmer {number}: {baths} Badezimmer-Zonen (erwartet genau 1)")
        # Zone-Namen je Zimmer eindeutig (uq_heating_zone_room_name).
        names = [z.zone_label for z in zone_rows]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            errors.append(f"Zimmer {number}: doppelte Zone-Namen {dupes}")

    # Kinderzimmer-Zonen exakt an den Soll-Zimmern.
    child_rooms_found = {r.zimmer_nummer for r in rows if r.room_type == "Kinderzimmer"}
    if child_rooms_found != CHILD_ROOMS:
        missing = sorted(CHILD_ROOMS - child_rooms_found)
        extra = sorted(child_rooms_found - CHILD_ROOMS)
        errors.append(f"Kinderzimmer-Zimmer falsch: fehlend={missing}, unerwartet={extra}")

    return errors


# ---------------------------------------------------------------------------
# DB: Step 0, Vorstufe, Wipe + Reseed
# ---------------------------------------------------------------------------


async def _ensure_room_types(session: AsyncSession) -> dict[str, RoomType]:
    """Step 0: RoomTypes Doppelzimmer/Suite sicherstellen (Default-Setpoints).

    Legt NUR fehlende an — KEINE Zonentyp-RoomTypes. Der Aufrufer ermittelt
    die neu angelegten Namen ueber den Vorher-Bestand (Diff). Gibt das
    ``name -> RoomType``-Mapping fuer die FK-Aufloesung zurueck.
    """
    result: dict[str, RoomType] = {}
    for name, description in ROOM_TYPE_DEFAULTS.items():
        existing = await session.scalar(select(RoomType).where(RoomType.name == name))
        if existing is not None:
            result[name] = existing
            continue
        rt = RoomType(
            name=name,
            description=description,
            is_bookable=True,
            default_t_occupied=_DEFAULT_T_OCCUPIED,
            default_t_vacant=_DEFAULT_T_VACANT,
            default_t_night=_DEFAULT_T_NIGHT,
        )
        session.add(rt)
        await session.flush()
        result[name] = rt
        logger.info("RoomType '%s' angelegt (id=%d).", name, rt.id)
    return result


async def _zones_with_devices(session: AsyncSession) -> list[tuple[int, str, str]]:
    """Blockierende Vorstufe: heating_zones mit zugeordnetem (aktivem) Device.

    Returns Liste ``(device_id, dev_eui, zone_name)`` — leer = wipe erlaubt.
    """
    stmt = (
        select(Device.id, Device.dev_eui, HeatingZone.name)
        .join(HeatingZone, Device.heating_zone_id == HeatingZone.id)
        .order_by(Device.id)
    )
    rows = (await session.execute(stmt)).all()
    return [(int(d_id), dev_eui, zone_name) for d_id, dev_eui, zone_name in rows]


async def _wipe_and_reseed(
    session: AsyncSession, rows: list[SeedRow], room_types: dict[str, RoomType]
) -> tuple[int, int]:
    """Loescht alle room + heating_zone und legt sie aus ``rows`` neu an.

    Laeuft in der Transaktion des Aufrufers (commit/rollback dort). Gibt
    ``(rooms_created, zones_created)`` zurueck.
    """
    # Explizit heating_zone vor room loeschen (room-Delete kaskadiert ohnehin,
    # aber explizit ist klarer). room-Delete kaskadiert occupancy/override/
    # rule_config(room)/scenario(room)/event_log (alle ondelete CASCADE);
    # globale + raumtyp-Configs (room_id NULL) bleiben.
    await session.execute(delete(HeatingZone))
    await session.execute(delete(Room))
    await session.flush()

    by_room: dict[str, list[SeedRow]] = {}
    for r in rows:
        by_room.setdefault(r.zimmer_nummer, []).append(r)

    rooms_created = 0
    zones_created = 0
    for number, zone_rows in by_room.items():
        head = zone_rows[0]
        room = Room(
            number=number,
            display_name=head.anzeigename or None,
            floor=head.etage,
            orientation=ORIENTATION_MAP[head.ausrichtung],
            room_type_id=room_types[head.zimmer_kategorie].id,
            status=RoomStatus.VACANT,
            guest_override_blocked=False,
            notes=None,
        )
        session.add(room)
        await session.flush()
        rooms_created += 1
        for z in sorted(zone_rows, key=lambda x: x.zone_index):
            session.add(
                HeatingZone(
                    room_id=room.id,
                    kind=KIND_MAP[z.room_type],
                    name=z.zone_label,
                )
            )
            zones_created += 1
    await session.flush()
    return rooms_created, zones_created


# ---------------------------------------------------------------------------
# Subcommand-Handler
# ---------------------------------------------------------------------------


def _resolve_path(args: argparse.Namespace) -> Path | None:
    return Path(args.path) if args.path else None


async def _cmd_validate(args: argparse.Namespace) -> int:
    """``validate [csv]``: Schema-Pruefung, kein Side-Effekt, keine DB."""
    path = _resolve_path(args)
    try:
        text = _read_csv_text(path)
    except (OSError, FileNotFoundError) as exc:
        print(f"[FAIL] CSV nicht lesbar: {exc}", file=sys.stderr)
        return 1

    rows, errors = parse_and_validate(text)
    if errors:
        print(f"[FAIL] {len(errors)} Schema-Fehler:")
        for err in errors:
            print(f"  - {err}")
        return 1
    room_count = len({r.zimmer_nummer for r in rows})
    print(f"[OK] {room_count} Zimmer / {len(rows)} Zonen validiert. Bereit fuer import.")
    return 0


async def _cmd_import(args: argparse.Namespace) -> int:
    """``import [csv] [--dry-run]``: Wipe + Reseed in EINER Transaktion."""
    path = _resolve_path(args)
    try:
        text = _read_csv_text(path)
    except (OSError, FileNotFoundError) as exc:
        print(f"[FAIL] CSV nicht lesbar: {exc}", file=sys.stderr)
        return 1

    rows, errors = parse_and_validate(text)
    if errors:
        print(f"[FAIL] {len(errors)} Schema-Fehler (import abgebrochen):")
        for err in errors:
            print(f"  - {err}")
        return 1

    async with SessionLocal() as session:
        # Blockierende Vorstufe: keine Vicki-Orphans.
        attached = await _zones_with_devices(session)
        if attached:
            print(
                f"[ABBRUCH] {len(attached)} Device(s) haengen an bestehenden "
                "heating_zones — KEIN Wipe. Betroffen:",
                file=sys.stderr,
            )
            for d_id, dev_eui, zone_name in attached:
                print(f"  - device_id={d_id} dev_eui={dev_eui} zone='{zone_name}'", file=sys.stderr)
            return 1

        # Step 0: RoomTypes sicherstellen (nur fehlende anlegen).
        existing_before = {
            name
            for (name,) in (
                await session.execute(
                    select(RoomType.name).where(RoomType.name.in_(ALLOWED_ROOM_TYPES))
                )
            ).all()
        }
        room_types = await _ensure_room_types(session)
        created_types = sorted(ALLOWED_ROOM_TYPES - existing_before)

        rooms_created, zones_created = await _wipe_and_reseed(session, rows, room_types)

        # Verify innerhalb der Transaktion.
        room_total = await session.scalar(select(func.count()).select_from(Room))
        zone_total = await session.scalar(select(func.count()).select_from(HeatingZone))
        if room_total != EXPECTED_ROOMS or zone_total != EXPECTED_ZONES:
            await session.rollback()
            print(
                f"[FAIL] Verify nach Reseed: {room_total} room / {zone_total} "
                f"heating_zone != erwartet {EXPECTED_ROOMS}/{EXPECTED_ZONES}. "
                "Transaktion zurueckgerollt.",
                file=sys.stderr,
            )
            return 1

        if args.dry_run:
            await session.rollback()
            print("[DRY-RUN] DB-Aenderungen zurueckgerollt.", file=sys.stderr)
        else:
            await session.commit()

    type_msg = (
        f"Step 0: RoomTypes angelegt: {created_types}."
        if created_types
        else "Step 0: RoomTypes Doppelzimmer/Suite standen bereits."
    )
    print(type_msg)
    print(
        f"Resultat: {rooms_created} room + {zones_created} heating_zone "
        f"{'(dry-run, verworfen)' if args.dry_run else 'angelegt'}."
    )
    return 0


# ---------------------------------------------------------------------------
# Argparse + Dispatch
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seed_rooms",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="CSV-Schema pruefen (kein Side-Effekt).")
    p_validate.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Pfad zur Seed-CSV. Default: eingebettete Package-Data.",
    )

    p_import = sub.add_parser("import", help="Wipe + Reseed room/heating_zone (eine Transaktion).")
    p_import.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Pfad zur Seed-CSV. Default: eingebettete Package-Data.",
    )
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="DB-Aenderungen werden zurueckgerollt (Smoke-Test).",
    )
    return parser


_DISPATCH = {
    "validate": _cmd_validate,
    "import": _cmd_import,
}


async def main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.command]
    return await handler(args)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
