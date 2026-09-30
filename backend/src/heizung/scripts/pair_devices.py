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
# Nur im direkten CLI-Aufruf, NICHT beim Import (Sprint 19 / PR B, T16).
#
# ``python -m heizung.scripts.<name>`` setzt ``__name__`` auf ``"__main__"``;
# ein ``import`` durch die Tests tut das nicht. Der Guard trennt damit genau
# die beiden Faelle.
#
# Anlass: die Zeile ``os.environ.setdefault("DATABASE_URL", ...)`` lief bei
# JEDEM Import mit. Sobald irgendein gesammeltes Testmodul dieses Skript
# importierte, hielt ``conftest._ensure_test_admin`` eine Datenbank fuer
# konfiguriert und versuchte zu migrieren — auch bei reinen
# Funktionstests. Lokal ohne Postgres wurden daraus 817 Verbindungsfehler
# statt 45 ehrlicher Skips, und die Skip-Logik der Tests war damit
# ausgehebelt, ohne dass es jemand sah.
#
# Die DATABASE_URL-Zeile ist **ganz** entfallen, nicht nur verschoben: sie
# setzte genau den Wert, den ``Settings.database_url`` ohnehin als Default
# traegt (``config.py``). Sie hatte also keine Wirkung ausser der
# Nebenwirkung.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.enums import UserRole  # noqa: E402
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
    HEARTBEAT_WAIT_MAX_S,
    SETPOINT_RESET_C,
    DeviceResult,
    format_report,
    run_batch_inbound_test,
    status_tag,
)
from heizung.scripts.pairing.csv_parser import (  # noqa: E402
    check_dev_eui_duplicates_in_csv,
    find_existing_dev_euis,
    parse_csv,
    validate_against_db,
)
from heizung.scripts.pairing.exceptions import ParseError  # noqa: E402
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


async def _lookup_user_id(session: AsyncSession, email: str) -> tuple[int | None, str | None]:
    """Email -> ``User.id``, aber nur fuer **aktive Admin-Konten**.

    Die Rollenpruefung spiegelt die Oberflaeche: Zuordnen, Trennen und
    Tauschen verlangen dort die Admin-Rolle (RUNBOOK 10h.0.2). Vorher pruefte
    dieser Lookup nur ``is_active``, eine Mitarbeiter-Adresse waere
    angenommen worden und stuende als Urheber im Audit.

    Gibt ``(None, Grund)`` zurueck statt nur ``None``: der Hotelier steht am
    Montage-Abend allein davor und braucht aus der Meldung heraus den
    naechsten Schritt, nicht nur ein "nicht gefunden".

    :return: ``(user_id, None)`` bei Erfolg, sonst ``(None, Klartext-Grund)``.
    """
    stmt = select(User.id, User.role, User.is_active).where(User.email == email)
    row = (await session.execute(stmt)).first()

    if row is None:
        return None, (
            f"Es gibt kein Konto mit der Adresse '{email}'. "
            "Adresse pruefen (Tippfehler?) oder die vorhandenen Konten auflisten — "
            "die Abfrage dafuer steht im RUNBOOK 10h.0.2."
        )

    user_id, role, is_active = row

    if not is_active:
        return None, (
            f"Das Konto '{email}' ist deaktiviert und kann deshalb nicht als "
            "Urheber eingetragen werden. Ein aktives Admin-Konto verwenden, "
            "oder das Konto in der Benutzerverwaltung wieder aktivieren."
        )

    if role is not UserRole.ADMIN:
        return None, (
            f"Das Konto '{email}' hat die Rolle '{role.value}'. Fuer diesen "
            "Aufruf ist ein Konto mit der Rolle 'admin' noetig — dieselbe "
            "Rolle, die in der Oberflaeche fuer Zuordnen, Trennen und Tauschen "
            "verlangt wird. Die vorhandenen Admin-Konten listet die Abfrage im "
            "RUNBOOK 10h.0.2."
        )

    return user_id, None


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
            user_id, reason = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(f"[FAIL] {reason} Import abgebrochen.", file=sys.stderr)
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


def _melde_phase(text: str) -> None:
    """Fortschritts-Meldung fuer einen Abschnitt (Sprint 19 / T10).

    Ein Lauf ueber 104 Geraete braucht bis zu sieben Wartefenster und damit
    ueber eine Stunde. Ohne Zwischenmeldung steht die Konsole stumm da, und
    ein stummer Lauf wird fuer haengend gehalten und abgebrochen — womit die
    Arbeit weg ist, die er gerade tut.
    """
    print(f"  * {text}", flush=True)


def _melde_geraet(result: DeviceResult) -> None:
    """Meldung, sobald EIN Geraete-Urteil feststeht und festgeschrieben ist."""
    zusatz = [t for t in (result.battery_note, result.reset_note) if t]
    schwanz = f" | {' | '.join(zusatz)}" if zusatz else ""
    print(
        f"  {status_tag(result.status):<12} {result.hardware_nummer}: {result.reason}{schwanz}",
        flush=True,
    )


async def _cmd_test(args: argparse.Namespace) -> int:
    """``test <device>``: der Batch-Eingangstest fuer genau ein Geraet.

    Sprint 19 (T11): bis hierher lief ein **zweiter**, eigener Ablauf mit
    Mitarbeiter-Rueckfragen (``inbound_test.run_inbound_test``). Zwei
    Mechanismen fuer dieselbe Pruefung heissen zwei Urteilslogiken, zwei
    Schwellensaetze und zwei Stellen, an denen eine Korrektur vergessen
    werden kann — die Sollwert-Schwelle ist in PR A genau deshalb
    auseinandergelaufen (25 gegen 28 Grad).

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

        user_id: int | None = None
        if args.user_email:
            user_id, reason = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(f"[FAIL] {reason}", file=sys.stderr)
                return 1

        print(
            f"Eingangstest fuer {device.label or device.dev_eui}. Class A: je "
            "Geraet ist immer nur ein Befehl unterwegs, der Lauf braucht "
            "deshalb bis zu fuenf Wartefenster.\n"
        )
        report = await run_batch_inbound_test(
            session,
            [device],
            timeout_s=args.timeout,
            poll_interval_s=args.poll_interval,
            valve_check=not args.no_valve_check,
            require_motor=args.require_motor,
            heartbeat_wait_s=args.heartbeat_wait,
            reset_setpoint=not args.no_reset,
            resume=args.resume,
            user_id=user_id,
            on_phase=_melde_phase,
            on_device=_melde_geraet,
        )
        await session.commit()

    print(format_report(report))
    return report.exit_code


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
            user_id, reason = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(f"[FAIL] {reason}", file=sys.stderr)
                return 1

        print(
            f"Batch-Eingangstest ueber {len(devices)} Pool-Geraet(e). "
            f"Zeitfenster {args.timeout} s je Sollwert-Schritt, Abfrage alle "
            f"{args.poll_interval} s."
        )
        print(
            "Class A: ein Downlink geht erst mit dem naechsten Uplink raus, und "
            "je Geraet ist immer nur ein Befehl unterwegs. Der Lauf braucht "
            "deshalb bis zu fuenf Zeitfenster: Vor-Check, zwei Sollwerte mit je "
            "einem Setzframe, FW-Abfrage."
        )
        if args.require_motor:
            print(
                "--require-motor: FAIL, wenn die Backplate fehlt oder kein "
                "Reading eine Ventilstellung traegt.\n"
            )
        else:
            print(
                "Ohne --require-motor: Geraete ohne Backplate werden als "
                "'ohne Motor' gefuehrt, der Motor bleibt ungeprueft.\n"
            )
        report = await run_batch_inbound_test(
            session,
            devices,
            timeout_s=args.timeout,
            poll_interval_s=args.poll_interval,
            valve_check=not args.no_valve_check,
            require_motor=args.require_motor,
            heartbeat_wait_s=args.heartbeat_wait,
            reset_setpoint=not args.no_reset,
            resume=args.resume,
            user_id=user_id,
            on_phase=_melde_phase,
            on_device=_melde_geraet,
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
            user_id, reason = await _lookup_user_id(session, args.user_email)
            if user_id is None:
                print(f"[FAIL] {reason}", file=sys.stderr)
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
        help="Eingangstest fuer EIN Geraet — derselbe Ablauf wie inbound-test.",
    )
    p_test.add_argument(
        "device",
        help="device.id (Integer) oder dev_eui (16 Hex-Zeichen). Auto-Detect.",
    )
    p_test.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Wartefenster je Schritt in Sekunden. Default {DEFAULT_TIMEOUT_S}.",
    )
    p_test.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL_S,
        help=f"Abstand zwischen zwei DB-Abfragen. Default {DEFAULT_POLL_INTERVAL_S}.",
    )
    p_test.add_argument(
        "--no-valve-check",
        action="store_true",
        help="Ventilkriterium abschalten. Dann zaehlt nur der Sollwert-Readback.",
    )
    p_test.add_argument(
        "--require-motor",
        action="store_true",
        help="Verlangt einen belegten Motortest — siehe inbound-test.",
    )
    p_test.add_argument(
        "--heartbeat-wait",
        type=int,
        default=HEARTBEAT_WAIT_MAX_S,
        help=f"Wartefenster des Vor-Checks auf den ersten frischen Uplink in "
        f"Sekunden. Default {HEARTBEAT_WAIT_MAX_S}. Kleiner setzen, wenn ein "
        "stummes Geraet den Lauf nicht aufhalten soll.",
    )
    p_test.add_argument(
        "--resume",
        action="store_true",
        help="Geraete mit endgueltigem Ergebnis aus einem frueheren Lauf "
        "ueberspringen. TIMEOUT gilt als offen und wird wiederholt. Fuer den "
        "zweiten Durchlauf nach einem Abbruch — jeder Downlink kostet Batterie.",
    )
    p_test.add_argument(
        "--no-reset",
        action="store_true",
        help=f"Sollwert danach NICHT auf {SETPOINT_RESET_C} Grad zuruecksetzen. "
        f"Ohne diesen Schalter endet jedes gepruefte Geraet auf "
        f"{SETPOINT_RESET_C} Grad statt auf dem Testwert.",
    )
    p_test.add_argument(
        "--user-email",
        default=None,
        help="Email des Aufrufers fuer den BusinessAudit-Eintrag.",
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
        "--require-motor",
        action="store_true",
        help="Verlangt einen belegten Motortest: FAIL statt 'ohne Motor', wenn "
        "die Backplate fehlt, UND FAIL statt PASS, wenn kein Reading eine "
        "Ventilstellung traegt. Pflicht fuer den Montage-Lauf (RUNBOOK 10h.4): "
        "dort IST das Geraet montiert, beides ist dann ein Befund und kein "
        "Tischzustand.",
    )
    p_batch.add_argument(
        "--heartbeat-wait",
        type=int,
        default=HEARTBEAT_WAIT_MAX_S,
        help=f"Wartefenster des Vor-Checks auf den ersten frischen Uplink in "
        f"Sekunden. Default {HEARTBEAT_WAIT_MAX_S}. Kleiner setzen, wenn ein "
        "stummes Geraet den Lauf nicht aufhalten soll.",
    )
    p_batch.add_argument(
        "--resume",
        action="store_true",
        help="Geraete mit endgueltigem Ergebnis aus einem frueheren Lauf "
        "ueberspringen. TIMEOUT gilt als offen und wird wiederholt. Fuer den "
        "zweiten Durchlauf nach einem Abbruch — jeder Downlink kostet Batterie.",
    )
    p_batch.add_argument(
        "--no-reset",
        action="store_true",
        help=f"Sollwert danach NICHT auf {SETPOINT_RESET_C} Grad zuruecksetzen. "
        f"Ohne diesen Schalter endet jedes gepruefte Geraet auf "
        f"{SETPOINT_RESET_C} Grad statt auf dem Testwert.",
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


def _reject_contradicting_flags(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Widersprechende Schalter beim Start abweisen, vor dem ersten Downlink.

    ``--no-valve-check`` schaltet das Ventilkriterium ab, ``--require-motor``
    verlangt es. Zusammen ergeben sie keine Lesart, die der Aufrufer gemeint
    haben kann.

    Bewusst ``parser.error`` und damit Exit 2 statt einer stillen Vorrangregel:
    eine Vorrangregel entscheidet fuer den Aufrufer und laesst ihn im Glauben,
    der andere Schalter habe gewirkt. Bei einem Lauf, der 104 Geraete anfasst
    und ueber eine Stunde braucht, faellt das erst am Ergebnis auf — und dann
    ist die Batterie verbraucht. Der Abbruch kommt **vor** dem ersten
    Downlink, weil argparse hier noch keinen Kontakt zur Hardware hatte.
    """
    if getattr(args, "no_valve_check", False) and getattr(args, "require_motor", False):
        parser.error(
            "Flags widersprechen sich: --no-valve-check schaltet das "
            "Ventilkriterium ab, --require-motor verlangt es. Genau einen von "
            "beiden angeben."
        )


async def main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _reject_contradicting_flags(parser, args)
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
