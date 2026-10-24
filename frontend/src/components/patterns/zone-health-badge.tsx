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

import type { ZoneHealthState, ZonenGeraeteLuecke } from "@/lib/api/types";

type Variant = "compact" | "detailed";

interface ZoneHealthBadgeProps {
  healthState: ZoneHealthState;
  variant?: Variant;
  className?: string;
  /**
   * Sprint 24d: was der Zone fehlt. Nur wirksam, wenn `healthState`
   * `no_device` ist — dann ersetzt die Lücke das Etikett. `null` lässt
   * alles wie vorher, damit kein Aufrufer sie setzen **muss**.
   */
  luecke?: ZonenGeraeteLuecke | null;
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

/**
 * Die drei Lücken, in Worten (Sprint 24d).
 *
 * **Befund des Betreibers, 24.10.2026.** Die Zone „Barbereich" trug „Kein
 * Gerät", obwohl ihr die Fühler-Vicki 027 zugeordnet ist. Das Kennzeichen
 * hatte recht und sagte das Falsche: der Zone fehlt kein Gerät, ihr fehlt
 * ein **Stellglied**. Ein Fühler, der nur misst, kann nicht heizen — das
 * ist seine Rolle und kein Mangel.
 *
 * „Kein Gerät" ist in dem Zustand der schlechteste von drei möglichen
 * Sätzen: er lässt nach einer fehlenden Zuordnung suchen, die gerade
 * gemacht wurde.
 */
const LUECKE: Record<
  ZonenGeraeteLuecke,
  { label: string; icon: string; badgeClass: string; hint: string }
> = {
  kein_stellglied: {
    label: "Kein Stellglied",
    icon: "sensors",
    badgeClass: "bg-surface-alt text-text-secondary",
    hint: "Die Zone misst, aber nichts kann heizen — kein Thermostat am Ventil und kein Relais.",
  },
  kein_fuehler: {
    label: "Kein Fühler",
    icon: "device_thermostat",
    badgeClass: "bg-surface-alt text-text-secondary",
    hint: "Es kann geheizt werden, aber niemand misst die Temperatur der Zone.",
  },
  beides: {
    label: "Kein Gerät",
    icon: "help",
    badgeClass: "bg-surface-alt text-text-tertiary",
    hint: "Der Zone ist weder ein Fühler noch ein Stellglied zugeordnet.",
  },
};

export function ZoneHealthBadge({
  healthState,
  variant = "compact",
  className,
  luecke = null,
}: ZoneHealthBadgeProps) {
  // **Bei ``no_device`` ersetzt die Lücke das Etikett** — sie ist die
  // genauere Aussage über denselben Umstand, und „Kein Gerät" war der
  // Befund des Betreibers.
  const cfg = luecke !== null && healthState === "no_device" ? LUECKE[luecke] : CONFIG[healthState];

  // **Sonst steht sie daneben.** Eine Zone mit einem gesunden Fühler und
  // ohne Stellglied ist „Zone OK" — und kann nicht heizen. Das zweite ist
  // die Nachricht, die man braucht; sie darf die erste aber nicht
  // verdecken, denn ein stummer Fühler ist dringender als ein fehlendes
  // Stellglied.
  const zusatz = luecke !== null && healthState !== "no_device" ? LUECKE[luecke] : null;

  const pille = (inhalt: { label: string; icon: string; badgeClass: string }) => (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium w-fit ${inhalt.badgeClass}`}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {inhalt.icon}
      </span>
      {inhalt.label}
    </span>
  );

  const pill = (
    <span className="inline-flex flex-wrap items-center gap-1">
      {pille(cfg)}
      {zusatz !== null ? (
        <span title={zusatz.hint} data-testid="zone-geraete-luecke">
          {pille(zusatz)}
        </span>
      ) : null}
    </span>
  );

  if (variant === "detailed") {
    return (
      <div
        className={`flex flex-col gap-0.5 ${className ?? ""}`.trim()}
        role="status"
        data-testid="zone-health-badge"
        data-health={healthState}
      >
        {pill}
        <span className="text-xs text-text-tertiary">{cfg.hint}</span>
      </div>
    );
  }

  return (
    <span className={`inline-flex flex-wrap items-center gap-1 ${className ?? ""}`.trim()}>
      <span
        role="status"
        title={cfg.hint}
        data-testid="zone-health-badge"
        data-health={healthState}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium ${cfg.badgeClass}`}
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
          {cfg.icon}
        </span>
        {cfg.label}
      </span>
      {/* Sprint 24d: die Luecke daneben, nicht statt. Eine Zone mit einem
          gesunden Fuehler und ohne Stellglied ist „Zone OK" — und kann
          nicht heizen. Das zweite ist die Nachricht, die man braucht. */}
      {zusatz !== null ? (
        <span
          role="status"
          title={zusatz.hint}
          data-testid="zone-geraete-luecke"
          data-luecke={luecke}
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium ${zusatz.badgeClass}`}
        >
          <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
            {zusatz.icon}
          </span>
          {zusatz.label}
        </span>
      ) : null}
    </span>
  );
}
