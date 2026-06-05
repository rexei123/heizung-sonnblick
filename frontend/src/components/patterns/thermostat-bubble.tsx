"use client";

/**
 * ThermostatBubble (Sprint 14b, T4).
 *
 * Kompakte Geräte-Kachel innerhalb einer ZoneCard: Bezeichnung +
 * HardwareStatusBadge + Ist-Temp + Batterie + Link auf die Detail-Seite.
 * Read-only Diagnose (AE-61) — KEINE Replace/Retire-Aktionen (die leben im
 * Geräte-Tab). Ist-Temp/Batterie aus dem in Sprint 14b erweiterten
 * ``device.latest_reading``.
 *
 * Wording §5.20: „Thermostat"; „Vicki" höchstens im Tooltip.
 */

import Link from "next/link";

import { BatteryBadge } from "@/components/patterns/battery-badge";
import { HardwareStatusBadge } from "@/components/patterns/hardware-status-badge";
import { formatTemperature } from "@/lib/format";
import type { Device } from "@/lib/api/types";

export function ThermostatBubble({ device }: { device: Device }) {
  const name = device.label ?? device.dev_eui;
  const reading = device.latest_reading;

  return (
    <div
      data-testid={`thermostat-bubble-${device.id}`}
      className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface px-3 py-2"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-text-primary text-sm truncate">{name}</span>
          <HardwareStatusBadge deviceId={device.id} variant="compact" />
        </div>
        <div className="mt-1 flex items-center gap-4 text-xs text-text-tertiary">
          <span title="Ist-Temperatur (letzte Messung)">
            <span className="material-symbols-outlined align-middle" aria-hidden style={{ fontSize: 14 }}>
              thermostat
            </span>{" "}
            {formatTemperature(reading?.temperature ?? null)}
          </span>
          {/* Sprint 15d (AE-65): Batterie als Badge (battery_state-Achse),
              Prozent nur im Tooltip — ersetzt die frühere formatPercent-Zahl. */}
          <BatteryBadge
            batteryState={device.battery_state}
            batteryPercent={reading?.battery_percent ?? null}
            variant="compact"
          />
        </div>
      </div>
      <Link
        href={`/devices/${device.id}` as never}
        className="shrink-0 text-xs text-primary hover:underline"
      >
        Detail →
      </Link>
    </div>
  );
}
