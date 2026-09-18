"""Zonen-Zuordnung bei der Montage (Sprint 17 / C8, D4).

Am Montagetag haengt ein Mitarbeiter die Vickis an die Heizkoerper. Abends
traegt der Hotelier nach, welches Geraet in welche Zone gewandert ist — mit
derselben Excel-Liste, aus der schon der Import kam, gefiltert auf die
Zimmer des Tages:

    pair_devices assign montage.csv --rooms 54,102 --dry-run
    pair_devices assign montage.csv --rooms 54,102

Warum CLI und nicht UI (D4)
---------------------------

Der vorhandene UI-Weg ist der Pairing-Wizard: vier Schritte, ein Geraet.
Fuer 14 Geraete an einem Abend waeren das 56 Klickstrecken. Die Liste ist
ohnehin schon da.

Warum ``--rooms`` Pflicht ist
-----------------------------

Die Montage-CSV enthaelt alle 103 Zonen. Ohne Filter wuerde der Abend-Lauf
Geraete Zimmern zuordnen, an denen noch niemand war. Die Zimmernummern des
Tages sind die bewusste Bestaetigung "diese habe ich montiert".

Alles oder nichts
-----------------

Der Pre-Flight sammelt **alle** Fehler und bricht dann ab, ohne etwas
geschrieben zu haben. Nicht beim ersten Fehler aufhoeren: der Hotelier soll
die Liste einmal korrigieren, nicht vierzehnmal nacheinander.

Geschrieben wird in **einer** Transaktion. Entweder alle Zuordnungen des
Abends stehen, oder keine.

Die Nachpruefung rollt nicht zurueck
------------------------------------

Nach dem Schreiben liest der Lauf je Geraet das juengste ``sensor_reading``
und prueft ``attached_backplate``. Meldet ein Geraet ``false`` oder hat es
zu lange nichts gesendet, ist das eine **Warnung**, kein Rueckbau: die
Zuordnung in der Datenbank ist richtig, das Geraet haengt nur (noch) nicht
oder hat sich seit der Montage nicht gemeldet. Rueckgaengig zu machen waere
falsch — dann muesste der Hotelier es am naechsten Abend erneut eintragen.
Exit-Code 2 trennt diesen Fall sichtbar vom harten Fehler (1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.rules.constants import WINDOW_STALE_THRESHOLD_MIN
from heizung.services.device_service import assign_zone

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.scripts.pairing.csv_row import PairingCsvRow

logger = logging.getLogger(__name__)

AUDIT_SOURCE = "assign_cli"


@dataclass(frozen=True, slots=True)
class PlannedAssignment:
    """Eine gepruefte Zuordnung, bereit zum Schreiben."""

    row_number: int
    device_id: int
    dev_eui: str
    hardware_nummer: str
    heating_zone_id: int
    zimmer_nummer: str
    zone_label: str


@dataclass
class AssignReport:
    """Ergebnis eines ``assign``-Laufs."""

    planned: list[PlannedAssignment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    written: int = 0
    unchanged: int = 0
    backplate_warnings: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.backplate_warnings:
            # Eigener Code: die Zuordnung steht, aber ein Geraet meldet sich
            # nicht als montiert. Kein Fehler, aber auch kein stilles OK.
            return 2
        return 0


def filter_rows(
    rows: Sequence[PairingCsvRow], rooms: Sequence[str]
) -> list[tuple[int, PairingCsvRow]]:
    """Nur die Zeilen der genannten Zimmer, Pool-Zeilen fliegen raus.

    Gibt ``(CSV-Zeilennummer, Row)`` zurueck — die Nummer wird hier
    berechnet und nicht spaeter rekonstruiert, sonst zeigt eine
    Fehlermeldung auf die Position *nach* dem Filtern und der Hotelier
    sucht in der falschen Zeile.
    """
    wanted = {r.strip() for r in rooms if r.strip()}
    return [
        (offset, row)
        for offset, row in enumerate(rows, start=2)
        if not row.is_pool_device and row.zimmer_nummer is not None and row.zimmer_nummer in wanted
    ]


async def _zone_id_for(session: AsyncSession, zimmer_nummer: str, zone_label: str) -> int | None:
    stmt = (
        select(HeatingZone.id)
        .join(Room, Room.id == HeatingZone.room_id)
        .where(Room.number == zimmer_nummer)
        .where(HeatingZone.name == zone_label)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def preflight(
    session: AsyncSession, rows: Sequence[tuple[int, PairingCsvRow]]
) -> tuple[list[PlannedAssignment], list[str]]:
    """Prueft alle Zeilen und sammelt **alle** Fehler.

    Geprueft wird je Zeile:

    1. Geraet zur DevEUI existiert ueberhaupt.
    2. Geraet ist nicht stillgelegt (``retired_at IS NULL``).
    3. Geraet ist im Pool (``heating_zone_id IS NULL``) — oder haengt bereits
       an genau der Zielzone (dann ist die Zeile ein No-op, kein Fehler).
    4. Zimmer + Zone existieren.
    5. Zielzone hat noch kein aktives Geraet.

    Zu (5): mehrere Vickis pro Zone sind fachlich vorgesehen (AE-51). Fuer
    den Montage-Abend ist ein zweites Geraet an derselben Zone aber fast
    immer ein Tippfehler — im Hotel Sonnblick ist jede Zone mit genau einem
    Geraet geplant. Deshalb ist das eine Regel **dieses Workflows**, nicht
    der Domaene; ``device_service.assign_zone`` kennt sie bewusst nicht.
    """
    planned: list[PlannedAssignment] = []
    errors: list[str] = []
    zielzonen: dict[int, int] = {}  # zone_id -> row_number (CSV-interne Dopplung)

    for offset, row in rows:
        # ``filter_rows`` hat Pool-Zeilen entfernt, also sind beide gesetzt.
        assert row.zimmer_nummer is not None
        assert row.zone_label is not None
        wo = (
            f"Zeile {offset} — Zimmer {row.zimmer_nummer} / {row.zone_label} (DevEUI {row.dev_eui})"
        )

        device = (
            await session.execute(select(Device).where(Device.dev_eui == row.dev_eui))
        ).scalar_one_or_none()
        if device is None:
            errors.append(f"{wo}: Geraet unbekannt — erst importieren.")
            continue
        if device.retired_at is not None:
            errors.append(f"{wo}: Geraet ist stillgelegt (retired_at gesetzt).")
            continue

        zone_id = await _zone_id_for(session, row.zimmer_nummer, row.zone_label)
        if zone_id is None:
            errors.append(f"{wo}: Zone nicht in der Datenbank.")
            continue

        if device.heating_zone_id is not None and device.heating_zone_id != zone_id:
            errors.append(
                f"{wo}: Geraet haengt bereits an Zone {device.heating_zone_id}. "
                "Umhaengen laeuft ueber den Tausch-Endpoint, nicht ueber assign."
            )
            continue

        if zone_id in zielzonen:
            errors.append(
                f"{wo}: Zielzone steht in der CSV zweimal "
                f"(auch Zeile {zielzonen[zone_id]}). Eine Zone, ein Geraet."
            )
            continue

        besetzt = (
            await session.execute(
                select(Device.id, Device.dev_eui)
                .where(Device.heating_zone_id == zone_id)
                .where(Device.retired_at.is_(None))
                .where(Device.dev_eui != row.dev_eui)
            )
        ).first()
        if besetzt is not None:
            errors.append(
                f"{wo}: Zone hat bereits ein aktives Geraet "
                f"(device_id={besetzt[0]}, DevEUI {besetzt[1]})."
            )
            continue

        zielzonen[zone_id] = offset
        planned.append(
            PlannedAssignment(
                row_number=offset,
                device_id=device.id,
                dev_eui=device.dev_eui,
                hardware_nummer=device.label or device.dev_eui,
                heating_zone_id=zone_id,
                zimmer_nummer=row.zimmer_nummer,
                zone_label=row.zone_label,
            )
        )
    return planned, errors


async def check_backplate(
    session: AsyncSession,
    planned: Sequence[PlannedAssignment],
    *,
    stale_after_min: int = WINDOW_STALE_THRESHOLD_MIN,
    now: datetime | None = None,
) -> list[str]:
    """Nachpruefung: meldet sich jedes zugeordnete Geraet als montiert?

    ``attached_backplate is True`` im juengsten, frischen Reading = in
    Ordnung. ``False`` oder zu alt = Warnung. Kein Rollback (siehe
    Modul-Docstring).
    """
    warnings: list[str] = []
    if not planned:
        return warnings
    reference = now or datetime.now(tz=UTC)
    threshold = reference - timedelta(minutes=stale_after_min)

    device_ids = [p.device_id for p in planned]
    stmt = (
        select(SensorReading)
        .where(SensorReading.device_id.in_(device_ids))
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    latest = {r.device_id: r for r in (await session.execute(stmt)).scalars().all()}

    for p in sorted(planned, key=lambda x: x.hardware_nummer):
        wo = f"Nr {p.hardware_nummer} — Zimmer {p.zimmer_nummer} / {p.zone_label}"
        reading = latest.get(p.device_id)
        if reading is None:
            warnings.append(f"{wo}: noch kein einziger Uplink.")
        elif reading.time < threshold:
            alter_min = int((reference - reading.time).total_seconds() // 60)
            warnings.append(
                f"{wo}: letzter Uplink vor {alter_min} Min "
                f"(aelter als {stale_after_min} Min) — Montage nicht bestaetigt."
            )
        elif reading.attached_backplate is None:
            warnings.append(f"{wo}: Uplink ohne Backplate-Feld (alter Codec / FW < 4.1).")
        elif reading.attached_backplate is False:
            warnings.append(f"{wo}: meldet NICHT montiert (attached_backplate=false).")
    return warnings


async def run_assign(
    session: AsyncSession,
    rows: Sequence[PairingCsvRow],
    rooms: Sequence[str],
    *,
    dry_run: bool = False,
    user_id: int | None = None,
    now: datetime | None = None,
) -> AssignReport:
    """Filtert, prueft, schreibt, prueft nach. Caller committet.

    Bei Pre-Flight-Fehlern wird **nichts** geschrieben. Bei ``dry_run``
    ebenfalls nicht — dann entfaellt auch die Backplate-Nachpruefung, weil
    sie ohne Zuordnung nichts aussagt.
    """
    report = AssignReport()
    selected = filter_rows(rows, rooms)
    if not selected:
        report.errors.append(
            f"Keine Zeile passt zu --rooms {','.join(rooms)}. Zimmernummern gegen die CSV pruefen."
        )
        return report

    planned, errors = await preflight(session, selected)
    report.planned = planned
    report.errors = errors
    if errors:
        return report

    if dry_run:
        return report

    for p in planned:
        _device, changed = await assign_zone(
            session,
            device_id=p.device_id,
            heating_zone_id=p.heating_zone_id,
            user_id=user_id,
            source=AUDIT_SOURCE,
        )
        if changed:
            report.written += 1
        else:
            report.unchanged += 1

    report.backplate_warnings = await check_backplate(session, planned, now=now)
    return report


def format_report(report: AssignReport, *, dry_run: bool) -> str:
    """Menschenlesbare Ausgabe."""
    lines: list[str] = []

    if report.errors:
        lines.append(f"[ABBRUCH] {len(report.errors)} Problem(e) — nichts geschrieben:")
        lines.extend(f"  - {e}" for e in report.errors)
        return "\n".join(lines)

    verb = "Wuerde zuordnen" if dry_run else "Zugeordnet"
    lines.append(f"{verb}: {len(report.planned)} Geraet(e)")
    for p in sorted(report.planned, key=lambda x: (x.zimmer_nummer, x.zone_label)):
        lines.append(
            f"  Nr {p.hardware_nummer:<6} {p.dev_eui}  ->  "
            f"Zimmer {p.zimmer_nummer} / {p.zone_label}"
        )

    if dry_run:
        lines.append("")
        lines.append("Vorschau. Zum Schreiben denselben Aufruf ohne --dry-run wiederholen.")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Geschrieben: {report.written} neu, {report.unchanged} bereits so zugeordnet.")

    if report.backplate_warnings:
        lines.append("")
        lines.append(
            f"[HINWEIS] {len(report.backplate_warnings)} Geraet(e) melden sich nicht "
            "als montiert. Die Zuordnung steht trotzdem — sie wird NICHT "
            "zurueckgenommen:"
        )
        lines.extend(f"  - {w}" for w in report.backplate_warnings)
        lines.append(
            "  Das ist normal, wenn das Geraet seit der Montage noch nicht gesendet "
            "hat (Vicki-Periodik ~15 Min). Morgen frueh erneut pruefen; meldet es "
            "sich dann immer noch nicht, sitzt es nicht richtig auf der Halterung."
        )
    else:
        lines.append("Alle zugeordneten Geraete melden sich als montiert.")
    return "\n".join(lines)
