r"""CLI-Entrypoint fuer das Pre-Pairing-Skript (Sprint 13a T6).

Aufruf via ``python -m heizung.scripts.pair_devices <subcommand>``.
Hotelier-Workflow im September 2026 (RUNBOOK §10h.2): CSV vom Office-
Laptop scp-en, dann via ``docker exec deploy-api-1 python -m
heizung.scripts.pair_devices ...`` aufrufen.

Subcommands:

- ``validate <csv>``   Pre-Flight (kein Side-Effekt). Liest CSV,
                        prueft Zone-Aufloesung + DevEUI-Duplikate.
- ``import <csv>``     Bulk-Anlage Device-Rows + DEVICE_PAIRED-Audit
                        + Open-Window-Detection-Downlink. ``--dry-run``
                        rollbackt DB-Aenderungen (Downlinks bleiben).
- ``test <device-id>``  6-Schritt-Eingangstest pro Vicki.
- ``list-pool``        Reserve-Pool-Devices (heating_zone_id IS NULL).

Aufruf-Beispiele:

    python -m heizung.scripts.pair_devices validate /tmp/pairings.csv
    python -m heizung.scripts.pair_devices import /tmp/pairings.csv \
        --user-email admin@hotel-sonnblick.at
    python -m heizung.scripts.pair_devices import /tmp/pairings.csv --dry-run
    python -m heizung.scripts.pair_devices test 47                  # via device.id
    python -m heizung.scripts.pair_devices test aabbccdd11223344    # via dev_eui
    python -m heizung.scripts.pair_devices test 47 --non-interactive
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
from heizung.scripts.pairing.csv_parser import (  # noqa: E402
    check_dev_eui_duplicates,
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

    async with SessionLocal() as session:
        db_errors = await validate_against_db(rows, session)
        dup_errors = await check_dev_eui_duplicates(rows, session)
    all_errors = db_errors + dup_errors

    if all_errors:
        print(f"[FAIL] {len(all_errors)} Validierungs-Fehler:")
        for err in all_errors:
            print(f"  - {err}")
        return 1
    print(f"[OK] {len(rows)} CSV-Rows validiert. Bereit fuer import.")
    return 0


async def _lookup_user_id(session: AsyncSession, email: str) -> int | None:
    """Email -> User.id. Erwartet aktiven User; None falls nicht gefunden."""
    stmt = select(User.id).where(User.email == email).where(User.is_active.is_(True))
    result: int | None = await session.scalar(stmt)
    return result


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
        # Pre-Flight.
        db_errors = await validate_against_db(rows, session)
        dup_errors = await check_dev_eui_duplicates(rows, session)
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

        # --dry-run-Warnung VOR pair_batch: ChirpStack-Downlinks gehen
        # auch im Dry-Run raus, weil MQTT-Publish nicht-transaktional ist.
        if args.dry_run:
            print(
                "[WARN] --dry-run aktiv: DB-Aenderungen werden zurueckgerollt. "
                "ChirpStack-Downlinks (Open-Window-Detection) werden GESENDET. "
                "Vickis aus der CSV erhalten Konfigurations-Befehle.",
                file=sys.stderr,
            )

        # Pair-Batch.
        results = await pair_batch(rows, session, user_id=user_id)

        if args.dry_run:
            await session.rollback()
            print(
                "[DRY-RUN] DB-Aenderungen zurueckgerollt. "
                "ChirpStack-Downlinks wurden trotzdem gesendet.",
                file=sys.stderr,
            )
        else:
            await session.commit()

    # Pro-Row-Output.
    counts = {"paired": 0, "skipped_exists": 0, "error": 0}
    status_tag = {"paired": "[OK]", "skipped_exists": "[SKIP]", "error": "[FAIL]"}
    for r in results:
        counts[r.status] += 1
        detail = r.error_msg or "ok"
        print(
            f"{status_tag[r.status]} Zeile {r.row_number}: DevEUI {r.dev_eui} "
            f"(device_id={r.device_id}, is_pool={r.is_pool}) -> {detail}"
        )

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
        )
    print(format_test_result(result))
    return 0 if result.overall_status == "passed" else 1


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
        help="Bulk-Anlage Device-Rows + DEVICE_PAIRED-Audit + OW-Downlink.",
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
        help="DB-Aenderungen werden zurueckgerollt. ChirpStack-Downlinks werden "
        "gesendet. Geeignet fuer Smoke-Test auf heizung-test.",
    )

    # test
    p_test = sub.add_parser(
        "test",
        help="6-Schritt-Eingangstest pro Vicki (RUNBOOK §10h.1).",
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
