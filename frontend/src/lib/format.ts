/**
 * Formatierungs-Helfer fuer die UI.
 *
 * Sprache: Deutsch, Sie-Form, sachlich.
 * Locale: de-AT (Hotel Sonnblick Kaprun).
 */

const DT = new Intl.DateTimeFormat("de-AT", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const RTF = new Intl.RelativeTimeFormat("de-AT", { numeric: "auto" });

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return DT.format(d);
}

/**
 * Relative Zeitangabe ("vor 5 Min", "vor 2 Tagen").
 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  const diffSec = Math.round((d.getTime() - Date.now()) / 1000);
  const abs = Math.abs(diffSec);

  if (abs < 60) return RTF.format(diffSec, "second");
  if (abs < 3600) return RTF.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return RTF.format(Math.round(diffSec / 3600), "hour");
  return RTF.format(Math.round(diffSec / 86400), "day");
}

/**
 * Kalendertag-Formatter: "YYYY-MM-DD" -> "DD.MM.YYYY", rein als String,
 * OHNE Date/Timezone. ``new Date("2026-06-06")`` wäre UTC-Mitternacht und
 * würde in westlichen Zeitzonen auf den Vortag kippen (§5.65-Falle); ein
 * Kalendertag (``list_date``) darf nie durch die UTC-Pipeline.
 */
export function formatCalendarDate(value: string | null | undefined): string {
  if (!value) return "–";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!m) return "–";
  return `${m[3]}.${m[2]}.${m[1]}`;
}

export function formatTemperature(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${v.toFixed(1)} °C`;
}

export function formatPercent(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${Math.round(v)} %`;
}

export function formatRssi(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${v} dBm`;
}

export function formatSnr(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${v.toFixed(1)} dB`;
}
