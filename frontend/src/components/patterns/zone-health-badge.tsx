"use client";

/**
 * ZoneHealthBadge (Sprint 14a, D6/D7).
 *
 * Zeigt den aggregierten Health-Zustand einer Heizzone (AE-51/AE-53).
 * Quelle ist ``device.heating_zone.health_state`` aus dem Device-Response
 * (kein eigener API-Call) — Co-Existenz mit dem Device-Level
 * ``HardwareStatusBadge``.
 *
 * - ``compact``: Pille (Icon + Label), Hint als ``title``-Tooltip.
 * - ``detailed``: Pille plus erklaerende Hint-Zeile.
 *
 * Wording §5.20: „Zone …" + „Thermostat" im Hint, kein „Vicki".
 */

import type { ZoneHealthState } from "@/lib/api/types";

type Variant = "compact" | "detailed";

interface ZoneHealthBadgeProps {
  healthState: ZoneHealthState;
  variant?: Variant;
  className?: string;
}

interface StateConfig {
  label: string;
  icon: string;
  badgeClass: string;
  hint: string;
}

const CONFIG: Record<ZoneHealthState, StateConfig> = {
  healthy: {
    label: "Zone OK",
    icon: "health_and_safety",
    badgeClass: "bg-success-soft text-success",
    hint: "Alle Thermostate der Zone senden plausibel.",
  },
  degraded: {
    label: "Zone Achtung",
    icon: "warning",
    badgeClass: "bg-warning-soft text-warning",
    hint: "Mindestens ein Thermostat der Zone ist eingeschränkt.",
  },
  silent: {
    label: "Zone Stumm",
    icon: "error",
    badgeClass: "bg-danger-soft text-danger",
    hint: "Alle Thermostate der Zone sind länger offline.",
  },
  no_device: {
    label: "Kein Gerät",
    icon: "help",
    badgeClass: "bg-surface-alt text-text-tertiary",
    hint: "Der Zone ist kein Thermostat zugeordnet.",
  },
};

export function ZoneHealthBadge({
  healthState,
  variant = "compact",
  className,
}: ZoneHealthBadgeProps) {
  const cfg = CONFIG[healthState];
  const pill = (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium w-fit ${cfg.badgeClass}`}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {cfg.icon}
      </span>
      {cfg.label}
    </span>
  );

  if (variant === "detailed") {
    return (
      <div className={`flex flex-col gap-0.5 ${className ?? ""}`.trim()} role="status">
        {pill}
        <span className="text-xs text-text-tertiary">{cfg.hint}</span>
      </div>
    );
  }

  return (
    <span
      role="status"
      title={cfg.hint}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium ${cfg.badgeClass} ${className ?? ""}`.trim()}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {cfg.icon}
      </span>
      {cfg.label}
    </span>
  );
}
