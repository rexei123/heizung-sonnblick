"use client";

/**
 * HardwareStatusBadge (Sprint 9.13c, überarbeitet Sprint 17 / C9).
 *
 * Zeigt, ob ein Thermostat auf seiner Wandhalterung sitzt. Quelle ist
 * ``sensor_reading.attached_backplate`` der letzten 30 Minuten, aggregiert
 * vom Endpoint ``GET /api/v1/devices/{id}/hardware-status``.
 *
 * **Was hier NICHT steht: ob das Gerät online ist.** Bis Sprint 16 hieß die
 * Pille „Aktiv" / „Inaktiv" mit der Unterzeile „Zuletzt: …" bzw. „noch nie".
 * Das liest sich wie ein Online-Status, gemessen wird aber die Montage. Am
 * Tisch — vor der Montage — ist ``attached_backplate=false`` der *erwartete*
 * Zustand (RUNBOOK §10h.4); die alte Beschriftung ließ dort jedes gesunde
 * Gerät als „Inaktiv — noch nie" erscheinen, während daneben „Batterie OK"
 * stand. Zwei Achsen, eine irreführende Beschriftung.
 *
 * Vier Zustände aus denselben Antwortfeldern plus der Zuordnung, ohne
 * Backend-Änderung:
 *
 * | ``frames_in_window`` | ``status`` | Pool | Anzeige |
 * |---|---|---|---|
 * | 0 | inactive | — | **Keine Daten (30 Min)** — kein verwertbarer Frame |
 * | > 0 | inactive | ja | **Im Lager** (grau) — gemeldet, noch nicht montiert |
 * | > 0 | inactive | nein | **Nicht montiert** (rot) — sitzt nicht, obwohl zugeordnet |
 * | ≥ 0 | active | — | **Montiert** |
 *
 * Der erste Fall war bisher nicht vom zweiten zu unterscheiden, obwohl er
 * etwas anderes bedeutet: kein Frame mit dem Feld heißt alter Codec, FW < 4.1
 * oder gar kein Uplink — nicht „hängt nicht".
 *
 * **Sprint 20:** Ein Pool-Gerät, das sich meldet und nicht montiert ist, war
 * rot mit der Unterzeile „noch nicht gemeldet" — zwei Fehlaussagen in einer
 * Zeile. Rot, weil der erwartete Zustand als Mangel gelesen wurde: im Lager
 * ist „nicht montiert" richtig. Und „noch nicht gemeldet", weil ``last_seen``
 * nur True-Frames zählt — ein Gerät, das sich alle zehn Minuten meldet, stand
 * da als hätte es nie gefunkt. Die Montage-Reihenfolge (RUNBOOK §10h.6) führt
 * genau durch diesen Zustand: montieren → Eingangstest, Gerät noch Pool →
 * ``assign``.
 *
 * - ``compact``: nur die Pille, Unterzeile als ``title``-Tooltip.
 * - ``detailed``: Pille plus Unterzeile.
 *
 * Für einen echten Online-Indikator wäre ``device.last_seen_at`` die Quelle
 * (wird vom MQTT-Subscriber gepflegt, heute in keiner Ansicht gerendert) —
 * eigener Badge, eigener Sprint.
 */

import { useHardwareStatus } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/format";

type Variant = "compact" | "detailed";

interface Props {
  deviceId: number;
  /**
   * Gerät liegt im Reserve-Pool (``heating_zone_id === null``). Pflicht-Prop,
   * kein Default: „nicht montiert" ist beim Pool-Gerät der erwartete Zustand
   * und beim zugeordneten ein Mangel. Ein Default würde die Unterscheidung
   * genau dort verschlucken, wo sie gebraucht wird.
   */
  isPool: boolean;
  variant?: Variant;
}

type MountState = "montiert" | "nicht_montiert" | "im_lager" | "keine_daten";

interface StateConfig {
  label: string;
  icon: string;
  badgeClass: string;
}

const CONFIG: Record<MountState, StateConfig> = {
  montiert: {
    label: "Montiert",
    icon: "check_circle",
    badgeClass: "bg-success-soft text-success",
  },
  nicht_montiert: {
    label: "Nicht montiert",
    icon: "link_off",
    badgeClass: "bg-danger-soft text-danger",
  },
  im_lager: {
    // Neutral, nicht rot: das Gerät tut, was es soll — es liegt und meldet.
    label: "Im Lager",
    icon: "inventory_2",
    badgeClass: "bg-surface-alt text-text-tertiary",
  },
  keine_daten: {
    // Kein Fehler, sondern Unwissen: im Fenster kam kein Frame, der das
    // Backplate-Feld ueberhaupt getragen haette.
    label: "Keine Daten (30 Min)",
    icon: "help",
    badgeClass: "bg-surface-alt text-text-tertiary",
  },
};

export function HardwareStatusBadge({ deviceId, isPool, variant = "compact" }: Props) {
  const { data, isLoading, error } = useHardwareStatus(deviceId);

  if (isLoading) {
    return (
      <span
        className="inline-block h-5 w-20 rounded-sm bg-surface-alt animate-pulse"
        aria-label="Hardware-Status laedt"
      />
    );
  }

  if (error || !data) {
    return (
      <span
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm bg-surface-alt text-text-tertiary text-xs"
        title="Hardware-Status nicht abrufbar"
        role="status"
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
          help
        </span>
        ?
      </span>
    );
  }

  const state: MountState =
    data.status === "active"
      ? "montiert"
      : data.frames_in_window === 0
        ? "keine_daten"
        : isPool
          ? "im_lager"
          : "nicht_montiert";

  const config = CONFIG[state];
  // „noch nicht gemeldet" gilt nur, wenn im Fenster gar kein Frame kam.
  // ``last_seen`` zählt ausschliesslich True-Frames — ein Gerät, das sich
  // meldet und nicht montiert ist, hat hier NULL und ist trotzdem nicht
  // stumm. Das war die zweite Fehlaussage in der alten Zeile.
  const subline = data.last_seen
    ? `Montiert zuletzt: ${formatRelative(data.last_seen)}`
    : data.frames_in_window > 0
      ? "meldet sich, nicht montiert"
      : "noch nicht gemeldet";

  const pill = (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium w-fit ${config.badgeClass}`}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {config.icon}
      </span>
      {config.label}
    </span>
  );

  if (variant === "detailed") {
    return (
      <div className="flex flex-col gap-0.5" role="status" data-testid="hardware-status">
        {pill}
        <span className="text-xs text-text-tertiary">{subline}</span>
      </div>
    );
  }

  return (
    <span role="status" title={subline} data-testid="hardware-status">
      {pill}
    </span>
  );
}
