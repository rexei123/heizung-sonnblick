/**
 * Formatierungs-Helfer fuer die UI.
 *
 * Sprache: Deutsch, Sie-Form, sachlich.
 * Locale: de-AT (Hotel Sonnblick Kaprun).
 */

/**
 * Zeitzone des Hotels. Fest verdrahtet, NICHT die Zeitzone des Browsers.
 *
 * Bis zum 26.09.2026 fehlte diese Angabe. Intl nimmt dann die Zone des
 * anzeigenden Geraets — was in Kaprun meist richtig aussieht und beim
 * Zugriff aus einer anderen Zone (Reise, Server-Rendering, Monitoring von
 * ausserhalb) still falsche Uhrzeiten zeigt. Ein Betriebszeitstempel
 * bezieht sich auf die Uhr des Hotels, nicht auf die des Betrachters.
 *
 * Quelle der Wahrheit ist ``global_config.timezone``; hier steht sie als
 * Konstante, weil Intl einen Wert zum Modul-Ladezeitpunkt braucht und das
 * Hotel einen Standort hat. Zieht das Haus um, aendert sich beides.
 */
export const HOTEL_TIMEZONE = "Europe/Vienna";

const DT = new Intl.DateTimeFormat("de-AT", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: HOTEL_TIMEZONE,
});

/** Wie DT, zusaetzlich mit Zeitzonen-Kuerzel ("26.09.2026, 10:38 MESZ"). */
const DT_TZ = new Intl.DateTimeFormat("de-AT", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: HOTEL_TIMEZONE,
  timeZoneName: "short",
});

const RTF = new Intl.RelativeTimeFormat("de-AT", { numeric: "auto" });

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return DT.format(d);
}

/**
 * Zeitstempel MIT Zeitzonen-Kuerzel.
 *
 * Fuer Stellen, an denen die Uhrzeit neben einer anderen Uhrzeit steht oder
 * mit einer Schwelle verglichen wird. Dort ist die fehlende Einheit keine
 * Kosmetik: am 26.09.2026 stand ein UTC-Eingang ("08:38") neben einer
 * Ortszeit-Schwelle ("09:00 Uhr"), beide ohne Kennzeichnung — daraus wurde
 * eine falsch gesetzte Schwelle und ein Waechter, der 21 Tage zu frueh
 * anschlug.
 */
export function formatDateTimeTz(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return DT_TZ.format(d);
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

/**
 * Geräte-Spannung in Volt, eine Dezimalstelle, Komma als Trennzeichen
 * (Sprint 20, AE-69).
 *
 * Eine Stelle, nicht zwei: der Codec liefert die Spannung in einem
 * 4-Bit-Nibble, also in 0,1-V-Schritten. Eine zweite Stelle wäre erfunden —
 * derselbe Fehler, den die Prozent-Anzeige gemacht hat.
 */
export function formatVolts(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${v.toFixed(1).replace(".", ",")} V`;
}

export function formatRssi(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${v} dBm`;
}

export function formatSnr(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return `${v.toFixed(1)} dB`;
}
