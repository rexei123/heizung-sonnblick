r"""CLI-Entrypoint fuer das Pre-Pairing-Skript (Sprint 13a T6).

Aufruf via ``python -m heizung.scripts.pair_devices <subcommand>``.
Hotelier-Workflow im September 2026 (RUNBOOK §10h.3): CSV vom Office-
Laptop scp-en, dann via ``docker exec deploy-api-1 python -m
heizung.scripts.pair_devices ...`` aufrufen.

Subcommands:

- ``validate <csv>``   Pre-Flight (kein Side-Effekt). Liest CSV,
                        prueft Zone-Aufloesung + DevEUI-Duplikate.
- ``import <csv>``     Bulk-Anlage Device-Rows + DEVICE_PAIRED-Audit.
                        ``--dry-run`` rollbackt die DB-Aenderungen.
                        **Sendet keine Downlinks** (Sprint 17 / E3).
- ``test <device-id>``  6-Schritt-Eingangstest pro Vicki.
- ``inbound-test --all-pool``  Batch-Eingangstest ueber ALLE Pool-Geraete
                        gleichzeitig, inkl. Firmware-Inventar (Sprint 17 / C4).
                        ``--devices 017,042`` statt ``--all-pool`` prueft nur
                        die genannten — fuer den zweiten Durchlauf ueber die
                        TIMEOUT-Geraete mit verlaengertem Fenster.
- ``assign <csv> --rooms 54,102``  Zonen-Zuordnung am Montage-Abend
                        (Sprint 17 / C8). ``--dry-run`` zeigt nur die Vorschau.
- ``list-pool``        Reserve-Pool-Devices (heating_zone_id IS NULL).

Sprint 17 (E3/C3): ``import`` ist ein reiner Datenbank-Vorgang. Die
Open-Window-Detection wird **nach** der Montage gesetzt, mit FW-Gate,
via ``python -m heizung.scripts.activate_open_window_detection``.

Aufruf-Beispiele:

    python -m heizung.scripts.pair_devices validate /tmp/pairings.csv
    python -m heizung.scripts.pair_devices import /tmp/pairings.csv \
        --user-email admin@hotel-sonnblick.at
    python -m heizung.scripts.pair_devices import /tmp/pairings.csv --dry-run
    python -m heizung.scripts.pair_devices test 47                  # via device.id
    python -m heizung.scripts.pair_devices test aabbccdd11223344    # via dev_eui
    python -m heizung.scripts.pair_devices test 47 --non-interactive
    python -m heizung.scripts.pair_devices test 47 --skip-backplate
    python -m heizung.scripts.pair_devices inbound-test --all-pool
    python -m heizung.scripts.pair_devices inbound-test --all-pool --timeout 7200
    python -m heizung.scripts.pair_devices inbound-test --devices 017,042         --timeout 14400
    python -m heizung.scripts.pair_devices assign /tmp/montage.csv         --rooms 54,102 --dry-run
    python -m heizung.scripts.pair_devices assign /tmp/montage.csv --rooms 54,102
    python -m heizung.scripts.pair_devices list-pool

Auf heizung-test/heizung-main via Docker:

    docker exec deploy-api-1 python -m heizung.scripts.pair_devices \
        validate /tmp/pairings.csv
    docker exec -it deploy-api-1 python -m heizung.scripts.pair_devices \
        test 47

Das ``-it`` ist nur fuer ``test``-Subcommand mit interaktivem Prompt
noetig; alle anderen Subcommands laufen ohne ``-it``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

# Stellen sicher, dass die App-Settings geladen werden koennen.
# Pattern aus backend/scripts/activate_open_window_detection.py.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung",
)

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.user import User  # noqa: E402
from heizung.scripts.pairing.assign import (  # noqa: E402
    format_report as format_assign_report,
)
from heizung.scripts.pairing.assign import (  # noqa: E402
    run_assign,
)
from heizung.scripts.pairing.batch_inbound_test import (  # noqa: E402
    DEFAULT_POLL_INTERVAL_S,
    DEFAULT_TIMEOUT_S,
    format_report,
    run_batch_inbound_test,
)
from heizung.scripts.pairing.csv_parser import (  # noqa: E402
    check_dev_eui_duplicates_in_csv,
    find_existing_dev_euis,
    parse_csv,
    validate_against_db,
)
from heizung.scripts.pairing.exceptions import ParseError  # noqa: E402
from heizung.scripts.pairing.inbound_test import (  # noqa: E402
    format_test_result,
    run_inbound_test,
)
from heizung.scripts.pairing.pairing_service import pair_batch  # noqa: E402
from heizung.services.device_service import get_pool_devices  # noqa: E402

logger = logging.getLogger("pair_devices")


# ---------------------------------------------------------------------------
# Subcommand-Handler
# ---------------------------------------------------------------------------


async def _cmd_validate(args: argparse.Namespace) -> int:
    """``validate <csv>``: Pre-Flight-Check, kein Side-Effekt."""
    csv_path = Path(args.path)
    try:
        rows = parse_csv(csv_path)
    except ParseError as exc:
        print(f"[FAIL] CSV-Parse-Fehler: {exc}")
        for err in exc.errors:
            print(f"  - {err}")
        return 1

    dup_errors = check_dev_eui_duplicates_in_csv(rows)
    async with SessionLocal() as session:
        db_errors = await validate_against_db(rows, session)
        existing = await find_existing_dev_euis(rows, session)
    all_errors = db_errors + dup_errors

    if all_errors:
        print(f"[FAIL] {len(all_errors)} Validierungs-Fehler:")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    print(f"[OK] {len(rows)} CSV-Rows validiert. Bereit fuer import.")
    # Sprint 17 (E4): Bestandsgeraete sind kein Fehler mehr, aber der
    # Hotelier soll vor dem Lauf wissen, welche Zeilen angereichert statt
    # angelegt werden.
    if existing:
        print(
            f"[INFO] {len(existing)} der {len(rows)} DevEUIs stehen bereits in der DB — "
            "diese Zeilen reichern Metadaten an, statt ein Geraet anzulegen:"
        )
        for dev_eui, device_id in sorted(existing.items()):
            print(f"  - {dev_eui} (device_id={device_id})")
    return 0


async def _lookup_user_id(session: AsyncSession, email: str) -> int | None:
    """Email -> User.id. Erwartet aktiven User; None falls nicht gefunden."""
    stmt = select(User.id).where(User.email == email).where(User.is_active.is_(True))
    result: int | None = await session.scalar(stmt)
    return result


def _filter_pool_devices(devices: Sequence[Device], raw: str) -> tuple[list[Device], list[str]]:
    """Waehlt aus den Pool-Geraeten die genannten aus.

    Erkannt wird, womit der Report die Geraete benennt: die
    ``hardware_nummer`` (``device.label``, z. B. ``017``) oder ersatzweise
    die DevEUI. Gross-/Kleinschreibung egal, Leerzeichen um die Kommas egal.

    Die Reihenfolge der Pool-Liste bleibt erhalten — nicht die Reihenfolge
    der Eingabe. Der Report sortiert ohnehin nach Nummer.

    :return: ``(ausgewaehlte Geraete, nicht gefundene Bezeichner)``
    """
    wanted = [token.strip() for token in raw.split(",") if token.strip()]
    lookup = {token.casefold() for token in wanted}

    selected = [
        dev
        for dev in devices
        if (dev.label or "").casefold() in lookup or dev.dev_eui.casefold() in lookup
    ]

    found = {(dev.label or "").casefold() for dev in selected} | {
        dev.dev_eui.casefold() for dev in selected
    }
    unknown = [token for token in wanted if token.casefold() not in found]
    return selected, unknown


_DEV_EUI_PATTERN = re.compile(r"^[0-9A-Fa-f]{16}$")


async def _resolve_device(session: AsyncSession, device_arg: str) -> Device | None:
    """``device_arg`` ist entweder Integer-ID oder 16-Hex-DevEUI. Auto-Detect.

    - Wenn Pattern ``^[0-9A-Fa-f]{16}$`` matched: Lookup ueber ``dev_eui``
      (lowercase-normalisiert, CLAUDE.md §5.13).
    - Sonst: Versuch ``int(device_arg)``, Lookup ueber PK.
    - Bei Parse-Fehler oder kein Match: ``None``.
    """
    if _DEV_EUI_PATTERN.match(device_arg):
        dev_eui = device_arg.lower()
        stmt = select(Device).where(Device.dev_eui == dev_eui)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    try:
        device_id = int(device_arg)
    except ValueError:
        return None
    return await session.get(Device, device_id)


async def _cmd_import(args: argparse.Namespace) -> int:
    """``import <csv> [--user-email <email>] [--dry-run]``: Bulk-Pairing."""
    csv_path = Path(args.path)
    try:
        rows = parse_csv(csv_path)
    except ParseError as exc:
        print(f"[FAIL] CSV-Parse-Fehler: {exc}")
        for err in exc.errors:
            print(f"  - {err}")
        return 1

    async with SessionLocal() as session:
        # Pre-Flight. Sprint 17 (E4): DevEUI-Duplikate INNERHALB der CSV
        # bleiben ein harter Abbruch; ein bereits vorhandenes Geraet ist
        # dagegen der Anreicherungs-Normalfall und kein Fehler mehr.
        db_errors = await validate_against_db(rows, session)
        dup_errors = check_dev_eui_duplicates_in_csv(rows)
        all_errors = db_errors + dup_errors
        if all_errors:
            print(f"[FAIL] {len(all_errors)} Pre-Flight-Fehler:")
            for err in all_errors:
                print(f"  - {err}")
            return 1

        # User-Lookup falls --user-email — keine stillschweigende None-
        # Degradierung, expliziter Abbruch bei unbekannter Email.
        user_id: int | None
        if args.user_email:
            user_id = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(
                    f"[FAIL] User-Email '{args.user_email}' nicht gefunden "
                    "oder inaktiv. Import abgebrochen.",
                    file=sys.stderr,
                )
                return 1
        else:
            user_id = None

        # Pair-Batch. Sprint 17 (C3): rein transaktional, kein Downlink —
        # ein --dry-run hat damit garantiert KEINEN Aussen-Effekt mehr.
        results = await pair_batch(rows, session, user_id=user_id)

        if args.dry_run:
            await session.rollback()
            print(
                "[DRY-RUN] DB-Aenderungen zurueckgerollt. Keine Downlinks gesendet.",
                file=sys.stderr,
            )
        else:
            await session.commit()

    # Pro-Row-Output.
    counts = {"paired": 0, "enriched": 0, "skipped_exists": 0, "conflict": 0, "error": 0}
    status_tag = {
        "paired": "[OK]",
        "enriched": "[ERG]",
        "skipped_exists": "[SKIP]",
        "conflict": "[KONFLIKT]",
        "error": "[FAIL]",
    }
    for r in results:
        counts[r.status] += 1
        detail = r.error_msg or "ok"
        if r.status in ("paired", "enriched") and r.filled:
            detail = f"{detail} (Felder: {', '.join(r.filled)})"
        print(
            f"{status_tag[r.status]} Zeile {r.row_number}: DevEUI {r.dev_eui} "
            f"(device_id={r.device_id}, is_pool={r.is_pool}) -> {detail}"
        )

    # B-Sprint13a-8 ist mit Sprint 17 (C3) gegenstandslos: seit dem Wegfall
    # des OW-Downlinks gibt es keinen error-Pfad mehr, der eine Device-Row
    # zuruecklaesst. "N errors" heisst jetzt eindeutig "N Zeilen ohne
    # Device-Row" — keine Disambiguation noetig.
    print(
        f"\nResultat: {counts['paired']} paired, "
        f"{counts['skipped_exists']} skipped, {counts['error']} errors."
    )
    return 0 if counts["error"] == 0 else 1


async def _cmd_test(args: argparse.Namespace) -> int:
    """``test <device> [--non-interactive]``: 6-Schritt-Eingangstest.

    ``device`` ist entweder ``device.id`` (Integer) oder ``dev_eui``
    (16 Hex-Zeichen). Auto-Detect via ``_resolve_device``.
    """
    async with SessionLocal() as session:
        device = await _resolve_device(session, args.device)
        if device is None:
            print(
                f"[FAIL] Device '{args.device}' nicht gefunden "
                "(weder als device.id noch als dev_eui).",
                file=sys.stderr,
            )
            return 1
        result = await run_inbound_test(
            device.id,
            session,
            interactive=not args.non_interactive,
            skip_backplate=args.skip_backplate,
        )
    print(format_test_result(result))
    return 0 if result.overall_status == "passed" else 1


async def _cmd_inbound_test(args: argparse.Namespace) -> int:
    """``inbound-test --all-pool``: Batch ueber alle Pool-Geraete.

    Keine interaktiven Rueckfragen — bei 104 Geraeten waeren das 208
    Tastendruecke. Das Ventilkriterium ersetzt die akustische Kontrolle.
    """
    async with SessionLocal() as session:
        devices = await get_pool_devices(session)
        if not devices:
            print("Pool ist leer — keine Geraete zu pruefen.")
            return 0

        if args.devices:
            pool_total = len(devices)
            devices, unknown = _filter_pool_devices(devices, args.devices)
            if unknown:
                # Hart abbrechen statt still weniger zu pruefen: ein Tippfehler
                # in der TIMEOUT-Liste wuerde sonst ein Geraet ueberspringen,
                # und der zweite Durchlauf ist genau der, der es klaeren soll.
                print(
                    f"[FAIL] Nicht im Pool gefunden: {', '.join(unknown)}. "
                    "Erwartet werden Hardware-Nummern wie im Report oder DevEUIs.",
                    file=sys.stderr,
                )
                return 1
            print(f"Auswahl: {len(devices)} von {pool_total} Pool-Geraeten.")

        user_id: int | None = None
        if args.user_email:
            user_id = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(
                    f"[FAIL] User-Email '{args.user_email}' nicht gefunden oder inaktiv.",
                    file=sys.stderr,
                )
                return 1

        print(
            f"Batch-Eingangstest ueber {len(devices)} Pool-Geraet(e). "
            f"Zeitfenster {args.timeout} s je Sollwert-Schritt, Abfrage alle "
            f"{args.poll_interval} s."
        )
        print(
            "Class A: ein Downlink geht erst mit dem naechsten Uplink raus. "
            "Der Lauf dauert im unguenstigen Fall zwei Zeitfenster.\n"
        )
        report = await run_batch_inbound_test(
            session,
            devices,
            timeout_s=args.timeout,
            poll_interval_s=args.poll_interval,
            valve_check=not args.no_valve_check,
            user_id=user_id,
        )
        await session.commit()

    print(format_report(report))
    return report.exit_code


async def _cmd_assign(args: argparse.Namespace) -> int:
    """``assign <csv> --rooms 54,102 [--dry-run]``: Zuordnung am Montage-Abend.

    Exit-Codes: 0 = alles zugeordnet und montiert gemeldet · 1 = Pre-Flight-
    Fehler, nichts geschrieben · 2 = zugeordnet, aber mindestens ein Geraet
    meldet sich nicht als montiert (kein Rollback).
    """
    csv_path = Path(args.path)
    try:
        # AppKey ist hier nicht noetig: die Montage-CSV wird ohne die Spalte
        # exportiert, damit das Geheimnis nicht ein zweites Mal herumliegt.
        rows = parse_csv(csv_path, require_app_key=False)
    except ParseError as exc:
        print(f"[FAIL] CSV-Parse-Fehler: {exc}")
        for err in exc.errors:
            print(f"  - {err}")
        return 1

    rooms = [r.strip() for r in args.rooms.split(",") if r.strip()]
    if not rooms:
        print("[FAIL] --rooms ist leer.", file=sys.stderr)
        return 1

    async with SessionLocal() as session:
        user_id: int | None = None
        if args.user_email:
            user_id = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(
                    f"[FAIL] User-Email '{args.user_email}' nicht gefunden oder inaktiv.",
                    file=sys.stderr,
                )
                return 1

        report = await run_assign(session, rows, rooms, dry_run=args.dry_run, user_id=user_id)
        if report.errors or args.dry_run:
            await session.rollback()
        else:
            await session.commit()

    print(format_assign_report(report, dry_run=args.dry_run))
    return report.exit_code


async def _cmd_list_pool(args: argparse.Namespace) -> int:
    """``list-pool``: Reserve-Devices (heating_zone_id IS NULL AND retired_at IS NULL).

    Sprint 13b.1 (AE-57): umgestellt auf ``get_pool_devices``-Helper aus
    ``services/device_service.py``. Lifecycle-Filter ist jetzt
    ``retired_at IS NULL`` (Single Source of Truth).
    """
    del args  # noqa: ARG001 — kein arg, Konsistenz mit anderen Handlern
    async with SessionLocal() as session:
        pool_devices = await get_pool_devices(session)

    if not pool_devices:
        print("Pool ist leer (keine Reserve-Devices).")
        return 0
    print(f"Reserve-Pool ({len(pool_devices)} Devices, heating_zone_id IS NULL):")
    print(f"  {'ID':<6} {'dev_eui':<18} {'model':<10} {'created_at':<20} label")
    for dev in pool_devices:
        ts = dev.created_at.strftime("%Y-%m-%d %H:%M:%S") if dev.created_at else "-"
        print(f"  {dev.id:<6} {dev.dev_eui:<18} {dev.model:<10} {ts:<20} {dev.label or '-'}")
    return 0


# ---------------------------------------------------------------------------
# Argparse + Dispatch
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pair_devices",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate
    p_validate = sub.add_parser(
        "validate",
        help="CSV einlesen + Pre-Flight (Zone-Lookup + Duplikat-Check). Kein Side-Effekt.",
    )
    p_validate.add_argument("path", help="Pfad zur Pairing-CSV.")

    # import
    p_import = sub.add_parser(
        "import",
        help="Bulk-Anlage Device-Rows + DEVICE_PAIRED-Audit (kein Downlink).",
    )
    p_import.add_argument("path", help="Pfad zur Pairing-CSV.")
    p_import.add_argument(
        "--user-email",
        default=None,
        help="Email des CLI-Aufrufers fuer BusinessAudit-user_id. Default: None (System-Trigger).",
    )
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="DB-Aenderungen werden zurueckgerollt. Seit Sprint 17 ohne jeden "
        "Aussen-Effekt — es werden keine Downlinks gesendet.",
    )

    # test
    p_test = sub.add_parser(
        "test",
        help="6-Schritt-Eingangstest pro Vicki (RUNBOOK §10h.4).",
    )
    p_test.add_argument(
        "device",
        help="device.id (Integer) oder dev_eui (16 Hex-Zeichen). Auto-Detect.",
    )
    p_test.add_argument(
        "--non-interactive",
        action="store_true",
        help="Setpoint-Schritte ohne User-Prompt (fuer CI/Smoke).",
    )
    p_test.add_argument(
        "--skip-backplate",
        action="store_true",
        help="Schritt 5 auslassen. Am Tisch ist attached_backplate=false "
        "erwartet (RUNBOOK 10h.4) — dort ist die Pruefung sinnlos.",
    )

    # inbound-test (Batch)
    p_batch = sub.add_parser(
        "inbound-test",
        help="Batch-Eingangstest ueber alle Pool-Geraete inkl. Firmware-Inventar.",
    )
    p_batch_scope = p_batch.add_mutually_exclusive_group(required=True)
    p_batch_scope.add_argument(
        "--all-pool",
        action="store_true",
        help="Alle Pool-Geraete pruefen (heating_zone_id IS NULL, nicht retired).",
    )
    p_batch_scope.add_argument(
        "--devices",
        default=None,
        help="Nur diese Pool-Geraete pruefen, kommagetrennt — Hardware-Nummern "
        "wie im Report ('017,042') oder DevEUIs. Fuer den zweiten Durchlauf "
        "ueber die TIMEOUT-Geraete mit verlaengertem Fenster, damit nicht alle "
        "104 Geraete das lange Zeitfenster belegen (RUNBOOK 10h.4).",
    )
    p_batch.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Wartefenster je Sollwert-Schritt in Sekunden. Default {DEFAULT_TIMEOUT_S}. "
        "Bei Geraeten mit bekannten Uplink-Luecken hoeher setzen — ein zu "
        "kurzes Fenster erzeugt Falsch-TIMEOUTs.",
    )
    p_batch.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL_S,
        help=f"Abstand zwischen zwei DB-Abfragen in Sekunden. Default {DEFAULT_POLL_INTERVAL_S}.",
    )
    p_batch.add_argument(
        "--no-valve-check",
        action="store_true",
        help="Ventilkriterium abschalten. Dann zaehlt nur der Sollwert-Readback.",
    )
    p_batch.add_argument(
        "--user-email",
        default=None,
        help="Email des Aufrufers fuer den BusinessAudit-Eintrag.",
    )

    # assign
    p_assign = sub.add_parser(
        "assign",
        help="Zonen-Zuordnung am Montage-Abend aus der Montage-CSV.",
    )
    p_assign.add_argument("path", help="Pfad zur Montage-CSV (ohne app_key-Spalte).")
    p_assign.add_argument(
        "--rooms",
        required=True,
        help="Zimmernummern des Tages, kommagetrennt (z.B. 54,102). Pflicht — "
        "die CSV enthaelt alle 103 Zonen, ohne Filter wuerden Geraete Zimmern "
        "zugeordnet, an denen noch niemand war.",
    )
    p_assign.add_argument(
        "--dry-run",
        action="store_true",
        help="Nur Vorschau. Es wird nichts geschrieben und nicht nachgeprueft.",
    )
    p_assign.add_argument(
        "--user-email",
        default=None,
        help="Email des Aufrufers fuer das DEVICE_ZONE_ASSIGNED-Audit.",
    )

    # list-pool
    sub.add_parser(
        "list-pool",
        help="Reserve-Pool-Devices (heating_zone_id IS NULL AND retired_at IS NULL).",
    )

    return parser


_DISPATCH = {
    "validate": _cmd_validate,
    "import": _cmd_import,
    "test": _cmd_test,
    "inbound-test": _cmd_inbound_test,
    "assign": _cmd_assign,
    "list-pool": _cmd_list_pool,
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
