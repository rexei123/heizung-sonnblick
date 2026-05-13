"use client";

/**
 * HardwareStatusBadge (Sprint 9.13c, B-LT-2-followup-1).
 *
 * Zeigt den Hardware-Status eines Vicki-Thermostats basierend auf
 * ``sensor_reading.attached_backplate`` der letzten 30 Min. Konsumiert
 * den Endpoint ``GET /api/v1/devices/{id}/hardware-status``.
 *
 * - ``compact``: Badge nur (Icon + Label „Aktiv"/„Inaktiv").
 * - ``detailed``: Badge plus Zeile „Zuletzt: vor X Min" bzw. „noch nie".
 */

import { useHardwareStatus } from "@/lib/api/hooks";
import { formatRelative } from "@/lib/format";

type Variant = "compact" | "detailed";

interface Props {
  deviceId: number;
  variant?: Variant;
}

export function HardwareStatusBadge({ deviceId, variant = "compact" }: Props) {
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

  const isActive = data.status === "active";
  const badgeClass = isActive
    ? "bg-success-soft text-success"
    : "bg-danger-soft text-danger";
  const icon = isActive ? "wifi" : "wifi_off";
  const label = isActive ? "Aktiv" : "Inaktiv";
  const lastSeenText = data.last_seen
    ? `Zuletzt: ${formatRelative(data.last_seen)}`
    : "noch nie";

  if (variant === "detailed") {
    return (
      <div className="flex flex-col gap-0.5" role="status">
        <span
          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium w-fit ${badgeClass}`}
        >
          <span
            className="material-symbols-outlined"
            aria-hidden
            style={{ fontSize: 14 }}
          >
            {icon}
          </span>
          {label}
        </span>
        <span className="text-xs text-text-tertiary">{lastSeenText}</span>
      </div>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium ${badgeClass}`}
      role="status"
      title={lastSeenText}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {icon}
      </span>
      {label}
    </span>
  );
}
