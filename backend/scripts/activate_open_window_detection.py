r"""Sprint 9.11x.b T8 — Bulk-Aktivierung Open-Window-Detection auf allen Vickis.

Sequenz pro Vicki (Devices mit ``kind='thermostat' AND heating_zone_id
IS NOT NULL``):

1. Phase 1: ``query_firmware_version`` (0x04) an alle Devices senden.
2. ``--wait-secs`` (default 60) warten — Vicki antworten asynchron beim
   naechsten Keepalive (Periodic-Reports default ~10 Min). 60 s ist
   best-effort; falls Vickis nicht innerhalb dieser Zeit antworten,
   bleibt ``device.firmware_version=NULL`` und das Device wird in
   Phase 3 geskippt. Re-Run idempotent.
3. Phase 3: pro Device FW-Version aus DB lesen, parsen, Tuple-Vergleich:
   - FW >= 4.2: ``set_open_window_detection(True, 10, Decimal("1.5"))``
     (Vendor-Bytes ``0x4501020F``) + ``get_open_window_detection`` (0x46)
   - FW <  4.2: skip + Warning (0x06-Variante kommt in B-9.11x.b-2)
   - FW NULL : skip + Warning (Vicki hat nicht geantwortet)
4. Tabellen-Output: dev_eui, label, fw_version, action, result.

Aufruf (auf heizung-test):

    docker exec deploy-api-1 python scripts/activate_open_window_detection.py
    docker exec deploy-api-1 python scripts/activate_open_window_detection.py --wait-secs 600

Lokal:

    cd backend; $env:ENVIRONMENT = "test"; $env:DATABASE_URL = "..."
    .\.venv\Scripts\python.exe scripts\activate_open_window_detection.py

S4-relevant: aktiviert produktive Vicki-Hardware-Konfiguration.
Idempotent — Re-Run sendet die gleichen 0x45-Bytes erneut, kein
Schaden. Logs siehe ``journalctl -u deploy-api`` (event_type=
MAINTENANCE_VICKI_CONFIG_REPORT).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from decimal import Decimal

# Stellen sicher, dass die App-Settings geladen werden koennen.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung",
)

from sqlalchemy import select  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.enums import DeviceKind  # noqa: E402
from heizung.services.downlink_adapter import (  # noqa: E402
    get_open_window_detection,
    query_firmware_version,
    set_open_window_detection,
)

logger = logging.getLogger("activate_ow")

# Vendor-Default fuer Hotelbetrieb (Cheat-Sheet §2): enabled,
# 10 Min Ventil-Schliessung, 1.5 °C Delta. AE-47-Konvention.
OW_DEFAULT_ENABLED: bool = True
OW_DEFAULT_DURATION_MIN: int = 10
OW_DEFAULT_DELTA_C: Decimal = Decimal("1.5")

# Mindest-FW fuer 0x45-Encoding-Variante (0.1 °C-Resolution). Vendor-Doku
# §01-open-window-detection.md.
MIN_FW_FOR_OW_SET: tuple[int, int] = (4, 2)


def _parse_fw_tuple(fw: str | None) -> tuple[int, int] | None:
    """``"4.5"`` -> ``(4, 5)``. None / Format-Fehler -> None.

    Akzeptiert auch ``"4.5.1"`` (3-Komponenten-Variante, falls Codec
    spaeter erweitert wird) — nimmt dann nur major.minor."""
    if fw is None:
        return None
    parts = fw.split(".")
    if len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


async def _phase1_query_firmware(devices: list[tuple[int, str, str | None]]) -> None:
    """Sendet 0x04 an alle Devices (sequentiell, 0.5 s Pause)."""
    print("\n=== Phase 1: FW-Query an alle Vickis ===")
    for _dev_id, dev_eui, label in devices:
        print(f"  -> 0x04  dev_eui={dev_eui}  label={label or '?'}")
        await query_firmware_version(dev_eui)
        await asyncio.sleep(0.5)


async def _phase3_activate_per_device(
    devices: list[tuple[int, str, str | None]],
) -> list[dict[str, str]]:
    """Pro Device FW lesen, ggf. 0x45 + 0x46 senden. Returns Tabellen-Rows."""
    print("\n=== Phase 3: pro Device FW pruefen + OW aktivieren ===")
    rows: list[dict[str, str]] = []
    async with SessionLocal() as session:
        for dev_id, dev_eui, label in devices:
            # Refresh: aktuelle firmware_version aus DB lesen.
            result = await session.execute(
                select(Device.firmware_version).where(Device.id == dev_id)
            )
            fw = result.scalar_one_or_none()
            fw_tuple = _parse_fw_tuple(fw)
            row: dict[str, str] = {
                "dev_eui": dev_eui,
                "label": label or "",
                "fw_version": fw or "(NULL)",
            }
            if fw_tuple is None:
                row["action"] = "skip"
                row["result"] = "no FW (Vicki hat nicht geantwortet)"
            elif fw_tuple < MIN_FW_FOR_OW_SET:
                row["action"] = "skip"
                row["result"] = (
                    f"FW<{MIN_FW_FOR_OW_SET[0]}.{MIN_FW_FOR_OW_SET[1]} (B-9.11x.b-2: 0x06-Fallback)"
                )
            else:
                try:
                    await set_open_window_detection(
                        dev_eui,
                        enabled=OW_DEFAULT_ENABLED,
                        duration_min=OW_DEFAULT_DURATION_MIN,
                        delta_c=OW_DEFAULT_DELTA_C,
                    )
                    await asyncio.sleep(0.5)
                    await get_open_window_detection(dev_eui)
                    row["action"] = "0x45+0x46 sent"
                    row["result"] = "verify-pending (siehe journalctl + naechster Keepalive)"
                except Exception as exc:  # noqa: BLE001 — Output-Sammlung wichtiger als Sofort-Fail
                    row["action"] = "0x45 failed"
                    row["result"] = f"error: {exc}"
            rows.append(row)
            print(f"  -> dev_eui={dev_eui} fw={row['fw_version']} action={row['action']}")
    return rows


def _print_table(rows: list[dict[str, str]]) -> None:
    """Tabellen-Output am Schluss — Spalten dev_eui | label | fw | action | result."""
    print("\n=== Ergebnis ===")
    if not rows:
        print("  (keine Devices)")
        return
    headers = ["dev_eui", "label", "fw_version", "action", "result"]
    widths = {h: max(len(h), max(len(r[h]) for r in rows)) for h in headers}
    print("  " + " | ".join(h.ljust(widths[h]) for h in headers))
    print("  " + "-+-".join("-" * widths[h] for h in headers))
    for r in rows:
        print("  " + " | ".join(r[h].ljust(widths[h]) for h in headers))


async def _load_target_devices() -> list[tuple[int, str, str | None]]:
    """Devices mit kind=thermostat UND heating_zone_id NOT NULL."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Device.id, Device.dev_eui, Device.label)
            .where(Device.kind == DeviceKind.THERMOSTAT)
            .where(Device.heating_zone_id.is_not(None))
            .order_by(Device.label.nulls_last(), Device.dev_eui)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]


async def main_async(wait_secs: int) -> int:
    devices = await _load_target_devices()
    if not devices:
        print("Keine Thermostat-Devices mit Heating-Zone gefunden — Abbruch.")
        return 0

    print(f"Gefunden: {len(devices)} Vicki(s) — beginne Bulk-Aktivierung.")
    await _phase1_query_firmware(devices)

    print(f"\n=== Warte {wait_secs} s auf FW-Antworten (Periodic-Cycle ~10 Min) ===")
    print("    Best-effort. FW=NULL nach Wait -> Device wird in Phase 3 geskippt.")
    await asyncio.sleep(wait_secs)

    rows = await _phase3_activate_per_device(devices)
    _print_table(rows)

    skipped = sum(1 for r in rows if r["action"] == "skip")
    activated = sum(1 for r in rows if r["action"].startswith("0x45"))
    failed = sum(1 for r in rows if "failed" in r["action"] or "error" in r["result"])
    print(
        f"\nTotal: {len(rows)}  aktiviert: {activated}  "
        f"geskippt: {skipped}  fehlgeschlagen: {failed}"
    )
    return 1 if failed > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wait-secs",
        type=int,
        default=60,
        help="Wartezeit (Sekunden) zwischen Phase 1 (FW-Query) und Phase 3 "
        "(Aktivierung). Default 60 (best-effort). Realistisch fuer 4 Vickis "
        "wegen 10-Min-Periodic-Cycle: 600-1200.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(main_async(args.wait_secs))


if __name__ == "__main__":
    sys.exit(main())
