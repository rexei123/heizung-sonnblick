"use client";

/**
 * BatteryBadge (Sprint 15d, AE-65).
 *
 * Zeigt den Batterie-Health-Zustand eines Geraets — die orthogonale dritte
 * Health-Achse neben ZoneHealthBadge/HardwareStatusBadge (§5.73). Quelle ist
 * ``device.battery_state`` aus dem Device-Response (KEIN eigener API-Call,
 * anders als HardwareStatusBadge) — prop-getrieben wie ZoneHealthBadge.
 *
 * 3+1 Zustaende aus ``battery_state`` (AE-65): ok (gruen) · warn (gelb) ·
 * kritisch (rot) · unbekannt (grau). KEINE 5-Stufen-Skala — der Badge ist an
 * die Achse gekoppelt, nicht an eine zweite Schwelle (B-15b-2 abgeschlossen).
 * Die exakte Prozentzahl steht NUR im ``title``-Tooltip (``batteryPercent``),
 * weil der Codec saettigt und 2-stellige Prozente Scheinpraezision sind
 * (AE-64 / §5.72).
 *
 * - ``compact``: Pille (Icon + Label), Tooltip als ``title``.
 * - ``detailed``: Pille plus erklaerende Hint-Zeile.
 *
 * Wording §5.20: „Thermostat"/„Batterie", kein „Vicki".
 */

import type { BatteryHealthState } from "@/lib/api/types";

type Variant = "compact" | "detailed";

interface BatteryBadgeProps {
  batteryState: BatteryHealthState;
  /** Jüngster battery_percent — NUR für den Tooltip (einzige Zahl-Stelle). */
  batteryPercent?: number | null;
  variant?: Variant;
  className?: string;
}

interface StateConfig {
  label: string;
  icon: string;
  badgeClass: string;
  hint: string;
}

const CONFIG: Record<BatteryHealthState, StateConfig> = {
  ok: {
    label: "Batterie OK",
    icon: "battery_full",
    badgeClass: "bg-success-soft text-success",
    hint: "Batterie ausreichend geladen.",
  },
  warn: {
    label: "Batterie schwach",
    icon: "battery_low",
    badgeClass: "bg-warning-soft text-warning",
    hint: "Batterie unter der Warnschwelle — Wechsel einplanen.",
  },
  kritisch: {
    label: "Batterie kritisch",
    icon: "battery_alert",
    badgeClass: "bg-danger-soft text-danger",
    hint: "Batterie fast leer — baldiger Wechsel nötig.",
  },
  unbekannt: {
    label: "Batterie unbekannt",
    icon: "battery_unknown",
    badgeClass: "bg-surface-alt text-text-tertiary",
    hint: "Kein aktueller Batterie-Messwert.",
  },
};

export function BatteryBadge({
  batteryState,
  batteryPercent = null,
  variant = "compact",
  className,
}: BatteryBadgeProps) {
  // Defensive: unbekannter/fehlender State (z. B. Altdaten) -> "unbekannt"
  // statt Crash (S5). Backend garantiert das Feld, Mocks evtl. nicht.
  const cfg = CONFIG[batteryState] ?? CONFIG.unbekannt;
  // Prozent ist die EINZIGE Stelle mit der Zahl (Tooltip), sonst der Hint.
  const title = batteryPercent != null ? `Batterie: ${batteryPercent} %` : cfg.hint;

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
      <div
        className={`flex flex-col gap-0.5 ${className ?? ""}`.trim()}
        role="status"
        title={title}
        data-testid="battery-badge"
        data-battery={batteryState}
      >
        {pill}
        <span className="text-xs text-text-tertiary">{cfg.hint}</span>
      </div>
    );
  }

  return (
    <span
      role="status"
      title={title}
      data-testid="battery-badge"
      data-battery={batteryState}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium ${cfg.badgeClass} ${className ?? ""}`.trim()}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {cfg.icon}
      </span>
      {cfg.label}
    </span>
  );
}
