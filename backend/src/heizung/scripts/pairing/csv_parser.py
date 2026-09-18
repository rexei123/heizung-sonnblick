"""CSV-Parser + DB-Pre-Flight-Checks fuer Mass-Pairing (Sprint 13a T3).

Konsumiert ``PairingCsvRow`` (T2) und liefert validierte Rows + Diff-
Reports zum DB-Stand zurueck. Trennt drei Phasen sauber:

1. ``parse_csv``: pure Parsing + Pydantic-Validation (kein DB-Zugriff).
2. ``validate_against_db``: Pre-Flight-Lookup Zimmer + Zone in heizung-DB.
3. ``check_dev_eui_duplicates_in_csv``: Duplikat-Check innerhalb der CSV.
4. ``find_existing_dev_euis``: welche DevEUIs stehen schon in der DB
   (Information, kein Fehler — siehe Docstring dort).

Convention (Phase-0 §F):
- Encoding ``utf-8-sig`` (Excel-Bomb-Toleranz fuer deutsche Excel-Exporte).
- Trennzeichen via ``csv.Sniffer().sniff(sample, delimiters=";,")`` —
  Excel-DE produziert oft Semikolon, Anglo-Excel Komma.
- Spalten-Header werden case-insensitive auf Pydantic-Feldnamen gemappt.
- Kopflose Spalten (leerer Header) werden ignoriert, nicht abgewiesen.

Spalten (Sprint 17 / E4): ``stockwerk``, ``zimmer_nummer``, ``zimmer_typ``,
``zone_label``, ``dev_eui``, ``app_key`` — dazu optional
``hardware_nummer``, ``app_eui``, ``serial_number``. Reihenfolge egal,
Gross-/Kleinschreibung egal, unbekannte Spalten werden ignoriert.

Sanity-Limit: 200 Zeilen. Hotel Sonnblick hat 110 Vickis (Sprint-13a-
Kontext); 200 ist sicherer Headroom mit Crash-Schutz gegen versehentliche
Full-Database-Dumps.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.scripts.pairing.csv_row import PairingCsvRow
from heizung.scripts.pairing.exceptions import ParseError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_ROWS = 200
"""Sanity-Limit. 110 Vickis im Hotel Sonnblick, 200 ist Headroom mit Schutz
gegen versehentliche Full-DB-Dumps."""

_NULLABLE_FIELDS = frozenset(
    {
        "stockwerk",
        "zimmer_nummer",
        "zimmer_typ",
        "zone_label",
        # Sprint 17 (E4/C2): optionale Metadaten. Leere Zelle == "nicht
        # erfasst" und darf nicht als Leerstring in die Validierung laufen
        # (app_eui wuerde sonst am Hex-Pattern scheitern).
        "hardware_nummer",
        "app_eui",
        "serial_number",
    }
)
"""Felder die leere Strings ("") als None interpretieren. dev_eui + app_key
muessen immer gesetzt sein."""


def _normalize_header(raw: str) -> str:
    """Spalten-Header case-insensitive + whitespace-strip auf Feldname mappen."""
    return raw.strip().lower()


def _row_to_dict(raw_row: dict[str, str], line_no: int) -> dict[str, object]:
    """DictReader-Row in Pydantic-Input-Dict umwandeln.

    - Header-Keys auf lowercase + stripped.
    - Leere Strings in NULLABLE-Feldern auf None (Pydantic-int|None erlaubt
      sonst kein '').
    - Unbekannte Spalten werden ignoriert (Pydantic extra='ignore' default).
    - **Kopflose Spalten werden uebersprungen** (Sprint 17 / C2): Excel-
      Exporte schleppen haeufig eine leere Spalte mit — etwa Spalte J, in
      der einmal etwas stand. ``csv.DictReader`` gibt ihr den Key ``""``
      (leerer Header) bzw. ``None`` (mehr Werte als Header-Spalten). Beides
      ist Rauschen, kein Datenfehler: der Hotelier soll die CSV nicht von
      Hand nachbearbeiten muessen, bevor 104 Geraete importiert werden.
      Zwei kopflose Spalten wuerden sonst als "doppelte Spalte ''"
      abgewiesen.

    :raises ParseError: wenn ein Header-Key kollidiert (z.B. ``Dev_EUI`` und
        ``dev_eui`` gleichzeitig).
    """
    cleaned: dict[str, object] = {}
    for raw_key, raw_val in raw_row.items():
        if raw_key is None:
            # DictReader-``restkey``: Zeile hat mehr Werte als der Header
            # Spalten. Ueberzaehlige Werte landen gesammelt unter None.
            continue
        key = _normalize_header(raw_key)
        if key == "":
            continue
        if key in cleaned:
            raise ParseError(f"Zeile {line_no}: doppelte Spalte '{key}' (case-insensitive).")
        value: object = raw_val.strip() if isinstance(raw_val, str) else raw_val
        if key in _NULLABLE_FIELDS and value == "":
            value = None
        cleaned[key] = value
    return cleaned


def parse_csv(path: Path) -> list[PairingCsvRow]:
    """CSV-Datei einlesen, validieren und Liste der Rows zurueckgeben.

    :raises ParseError: bei strukturellen Problemen (zu viele Zeilen, kein
        Trennzeichen, kein Header) ODER wenn mindestens eine Row die
        Pydantic-Validation nicht besteht. ``ParseError.errors`` enthaelt
        dann pro fehlerhafter Zeile eine Nachricht.
    """
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ParseError("CSV-Datei ist leer.")

    # Sniffer braucht ein Sample, ueblicherweise erste paar KB.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
    except csv.Error as exc:
        raise ParseError(f"Trennzeichen konnte nicht erkannt werden: {exc}") from exc

    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if reader.fieldnames is None:
        raise ParseError("CSV-Datei hat keinen Header.")

    rows: list[PairingCsvRow] = []
    errors: list[str] = []
    # DictReader liefert dict-per-row; line_no = 2 fuer erste Daten-Zeile
    # (Zeile 1 ist Header).
    for offset, raw_row in enumerate(reader, start=2):
        if offset - 1 > MAX_ROWS:
            raise ParseError(
                f"CSV ueberschreitet {MAX_ROWS}-Zeilen-Limit (gestoppt bei Zeile {offset})."
            )
        try:
            cleaned = _row_to_dict(raw_row, offset)
        except ParseError as exc:
            errors.append(str(exc))
            continue
        try:
            rows.append(PairingCsvRow.model_validate(cleaned))
        except ValidationError as exc:
            # Pydantic-Errors kompakt: nur die Messages, ohne Loc-Paths.
            msgs = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            errors.append(f"Zeile {offset}: {msgs}")

    if errors:
        raise ParseError(f"{len(errors)} Zeile(n) mit Validierungs-Fehlern.", errors=errors)
    return rows


async def validate_against_db(
    rows: list[PairingCsvRow],
    session: AsyncSession,
) -> list[str]:
    """Pre-Flight: pro Active-Row pruefen ob Zimmer + Zone in DB existieren.

    Active-Row: ``row.is_pool_device == False`` (zimmer_nummer + zone_label
    beide gesetzt). Pool-Rows brauchen keinen DB-Lookup.

    Lookup-Pfad: ``room.number == str(row.zimmer_nummer)`` JOIN
    ``heating_zone.room_id == room.id`` AND ``heating_zone.name == row.zone_label``.

    Hinweis: ``Room.number`` ist VARCHAR(20) im Schema (kann "101", "201b"
    sein); CSV-``zimmer_nummer`` ist int. Konvertierung via ``str()``.
    ``HeatingZone.name`` ist VARCHAR(100) (Modell-Feldname ``name``, NICHT
    ``label`` — die CSV-Spalte heisst ``zone_label`` aus Hotelier-Sprache,
    wird auf das DB-Feld ``name`` gemappt).

    :return: Liste von Diff-Messages. Leere Liste = alle Active-Rows haben
        passende Zone in DB.
    """
    errors: list[str] = []
    for offset, row in enumerate(rows, start=2):
        if row.is_pool_device:
            continue
        # zimmer_nummer / zone_label sind durch is_pool_device-Check garantiert
        # gesetzt; explicit assertions fuer mypy.
        assert row.zimmer_nummer is not None
        assert row.zone_label is not None
        stmt = (
            select(HeatingZone.id)
            .join(Room, Room.id == HeatingZone.room_id)
            .where(Room.number == str(row.zimmer_nummer))
            .where(HeatingZone.name == row.zone_label)
            .limit(1)
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            errors.append(
                f"CSV Zeile {offset}: Zimmer {row.zimmer_nummer} mit Zone "
                f"'{row.zone_label}' fehlt in DB."
            )
    return errors


def check_dev_eui_duplicates_in_csv(rows: list[PairingCsvRow]) -> list[str]:
    """Duplikat-Check **innerhalb** der CSV. Reine Funktion, kein DB-Zugriff.

    Dieselbe DevEUI zweimal in einer Datei ist ein echter Datenfehler
    (Copy-Paste im Excel, zwei Zeilen fuer dasselbe Geraet) und bleibt ein
    harter Abbruchgrund.

    :return: Liste von Konflikt-Messages mit den kollidierenden Zeilen-
        Nummern. Leere Liste = OK.
    """
    errors: list[str] = []
    seen: dict[str, int] = {}
    for offset, row in enumerate(rows, start=2):
        if row.dev_eui in seen:
            errors.append(
                f"DevEUI {row.dev_eui} in CSV mehrfach (Zeilen {seen[row.dev_eui]}, {offset})."
            )
        else:
            seen[row.dev_eui] = offset
    return errors


async def find_existing_dev_euis(
    rows: list[PairingCsvRow],
    session: AsyncSession,
) -> dict[str, int]:
    """DevEUIs aus der CSV, die bereits als ``device``-Row existieren.

    Bewusst KEIN ``retired_at IS NULL``-Filter (Sprint 13b.1, AE-57).
    Migration 0018 hat die Voll-Unique-Constraint auf ``dev_eui`` durch
    einen Partial-Unique-Index ersetzt
    (``ix_device_dev_eui_active_unique WHERE retired_at IS NULL``), der
    DevEUI-Wiederverwendung nach Werksreset technisch erlaubt. Auch ein
    retired Geraet zaehlt hier als "existiert" — Re-Pair nach Werksreset
    laeuft ueber den Sprint-13b-Tausch-Endpoint mit explizitem
    ``DEVICE_REPLACED``-Audit, nicht ueber den CSV-Import.

    **Sprint 17 (E4/C2) — Verhaltensaenderung.** Bis Sprint 16 war ein
    bereits vorhandenes Geraet ein Pre-Flight-**Fehler** und brach den
    gesamten Import ab. Das ist mit der Metadaten-Anreicherung nicht mehr
    haltbar: die vier Testgeraete (Vicki-001..004) stehen in der DB und
    sollen aus derselben CSV ihre AppEUI und Seriennummer bekommen. Ein
    Abbruch waere genau der Fall, den E4 ermoeglichen soll. Die Existenz
    ist deshalb jetzt eine **Information** — der Pairing-Service
    entscheidet pro Zeile zwischen Anreichern und Konflikt.

    :return: Mapping ``dev_eui -> device.id``. Leeres Dict = alles neu.
    """
    if not rows:
        return {}
    dev_euis = [row.dev_eui for row in rows]
    stmt = select(Device.dev_eui, Device.id).where(Device.dev_eui.in_(dev_euis))
    result = await session.execute(stmt)
    return dict(result.all())  # type: ignore[arg-type]  # Row[str, int] -> (str, int)
