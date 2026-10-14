/**
 * KpiCard — eine Dashboard-Kachel (Sprint 14c).
 *
 * Label + grosse Zahl + optionaler Sub-Wert + Material-Symbol-Icon-Slot.
 * Token-basierte Tones (Konvention wie ZoneHealthBadge / HardwareStatusBadge):
 * ``success-soft`` / ``warning-soft`` / ``danger-soft`` / ``neutral``.
 * Loading -> Skeleton; error -> dezenter „—" mit warning-Tone.
 *
 * Praesentationskomponente ohne eigene Hooks/Daten — wird von der
 * Dashboard-Page (``app/page.tsx``) gefuettert.
 */

import { cn } from "@/lib/utils";

export type KpiTone = "neutral" | "success-soft" | "warning-soft" | "danger-soft";

const TONE_ICON_CLASS: Record<KpiTone, string> = {
  neutral: "bg-surface-alt text-text-secondary",
  "success-soft": "bg-success-soft text-success",
  "warning-soft": "bg-warning-soft text-warning",
  "danger-soft": "bg-danger-soft text-danger",
};

interface KpiCardProps {
  label: string;
  value: string | number;
  subValue?: string;
  /**
   * Zweite, kleinere Zeile unter `subValue` (Sprint 21, B-21-2).
   *
   * Für eine Nebenzahl, die die Kachel **nicht** färbt und nicht in ihren
   * Zähler gehört — heute „3 im Lager" unter „101 von 101". Der Hotelier
   * hat diese Form der dritten Kachel vorgezogen: eine Zahl weniger im
   * Tagesblick, die Aufschlüsselung an der Stelle, wo man sie liest.
   *
   * Wird im Fehlerfall **nicht** gerendert — dann steht dort „Wert nicht
   * verfügbar", und eine Nebenzahl neben einem fehlenden Hauptwert wäre
   * eine Behauptung über Daten, die nicht angekommen sind.
   */
  note?: string;
  /** Material-Symbol-Name, z. B. "thermostat". */
  icon: string;
  tone?: KpiTone;
  loading?: boolean;
  error?: boolean;
}

export function KpiCard({
  label,
  value,
  subValue,
  note,
  icon,
  tone = "neutral",
  loading = false,
  error = false,
}: KpiCardProps) {
  if (loading) {
    return (
      <div
        data-testid="kpi-card"
        aria-busy="true"
        className="h-28 rounded-lg border border-border bg-surface p-4 shadow-sm"
      >
        <div className="h-full w-full animate-pulse rounded bg-surface-alt" />
      </div>
    );
  }

  const iconToneClass = error ? TONE_ICON_CLASS["warning-soft"] : TONE_ICON_CLASS[tone];

  return (
    <div
      data-testid="kpi-card"
      className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm"
    >
      <span
        className={cn(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-md",
          iconToneClass,
        )}
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 24 }}>
          {icon}
        </span>
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-text-secondary">{label}</p>
        <p className="text-2xl font-medium text-text-primary">{error ? "—" : value}</p>
        {error ? (
          <p className="mt-0.5 text-xs text-warning">Wert nicht verfügbar</p>
        ) : subValue ? (
          <p className="mt-0.5 text-xs text-text-tertiary">{subValue}</p>
        ) : null}
        {!error && note ? (
          <p className="mt-0.5 text-[11px] leading-tight text-text-tertiary">{note}</p>
        ) : null}
      </div>
    </div>
  );
}
