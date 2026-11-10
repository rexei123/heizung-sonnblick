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

export type KpiTone =
  "neutral" | "success-soft" | "warning-soft" | "danger-soft";

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
    // Das Skelett **ahmt den Aufbau der echten Karte nach**, statt eine
    // feste Höhe zu setzen. Vorher stand hier `h-28` (112 px) — eine Zahl,
    // die niemand nachrechnen konnte und die nach der zweiten Zusatzzeile
    // (Sprint 21) nicht mehr passte: beim Laden war das Raster 112 px hoch,
    // danach 118, und die Seite ist bei jedem Aufruf gesprungen.
    //
    // Die vier Zeilen tragen deshalb **dieselben Typografie-Klassen** wie
    // die echte Karte (`text-sm`, `text-2xl`, `text-xs`,
    // `text-[11px] leading-tight`) und je ein `&nbsp;` als Inhalt. Damit
    // ist die Höhe **abgeleitet**, nicht nachgerechnet: wer eine Klasse
    // ändert, ändert beide Seiten in derselben Zeile.
    //
    // Ein erster Versuch mit festen Balkenhöhen (`h-5`, `h-8`, …) lag
    // 6,75 px daneben — gemessen, nicht geschätzt. Genau das ist der
    // Grund gegen Zahlen an dieser Stelle.
    return (
      <div
        data-testid="kpi-card"
        aria-busy="true"
        className="flex h-full items-start gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm"
      >
        <span className="h-10 w-10 shrink-0 animate-pulse rounded-md bg-surface-alt" />
        <div className="min-w-0 flex-1">
          <p className="text-sm">
            <span className="inline-block w-2/3 animate-pulse rounded bg-surface-alt">
              &nbsp;
            </span>
          </p>
          <p className="text-2xl font-medium">
            <span className="inline-block w-1/2 animate-pulse rounded bg-surface-alt">
              &nbsp;
            </span>
          </p>
          <p className="mt-0.5 text-xs">
            <span className="inline-block w-3/4 animate-pulse rounded bg-surface-alt">
              &nbsp;
            </span>
          </p>
          <p className="mt-0.5 text-[11px] leading-tight">
            <span className="inline-block w-1/2 animate-pulse rounded bg-surface-alt">
              &nbsp;
            </span>
          </p>
        </div>
      </div>
    );
  }

  const iconToneClass = error
    ? TONE_ICON_CLASS["warning-soft"]
    : TONE_ICON_CLASS[tone];

  return (
    // `h-full`, damit die Karte die Zeilenhöhe des Rasters ausfüllt — das
    // Raster selbst macht alle Zeilen gleich hoch (`auto-rows-fr` in
    // `app/page.tsx`). `items-start` hält den Inhalt **oben**: eine Karte
    // mit einer Zeile soll ihren Wert auf derselben Linie zeigen wie eine
    // mit drei, nicht in der Mitte des freien Platzes schweben.
    <div
      data-testid="kpi-card"
      className="flex h-full items-start gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm"
    >
      <span
        className={cn(
          // `overflow-hidden` klemmt den **Ligatur-Namen** ab, solange die
          // Schrift „Material Symbols" noch nicht geladen ist: bis dahin
          // rendert der Browser `local_fire_department` als Text, und der
          // läuft über den 40-px-Kasten hinaus ins Etikett daneben.
          //
          // **Richtigstellung vom 10.11.2026, in eigener Sache.** Hier
          // stand zuerst, die Klasse halte die *Kachelhöhe* unabhängig vom
          // Schriftladen. Das ist falsch, und eine Mutationsprobe hat es
          // gezeigt: Klasse entfernt → alle neun Layout-Tests blieben
          // grün, auch der mit blockierter Schrift. Die Höhe hängt an
          // `h-10`, also an einer festen Zahl, und die gilt mit und ohne
          // Schrift. Die Klasse ist eine **Sichtbarkeits**-Verbesserung,
          // keine Layout-Absicherung — und als solche beschrieben.
          "flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-md",
          iconToneClass,
        )}
      >
        {/* `text-2xl` statt `style={{ fontSize: 24 }}`: dieselbe Größe
            (1.5rem = 24px) als Token, kein Inline-Style. */}
        <span
          className="material-symbols-outlined text-2xl leading-none"
          aria-hidden
        >
          {icon}
        </span>
      </span>
      <div className="min-w-0 flex-1">
        {/* Das Etikett kürzt seit jeher. Neu ist der `title`: bei zwei
            Spalten (Tablet, 768 px) ist die Karte am schmalsten, und
            „Befehle nicht angenommen" steht dort als „Befehle nicht
            angenomm…". Gemessen am 10.11.2026; auf dem Telefon (eine
            breite Spalte) und am Rechner passt es. Ein kürzeres Wort
            wäre die bessere Lösung — das ist eine Benennungsfrage und
            gehört dem Betreiber, nicht diesem PR. */}
        <p className="truncate text-sm text-text-secondary" title={label}>
          {label}
        </p>
        {/* **Der große Wert bricht nie um.** `truncate` setzt
            `white-space: nowrap`, `overflow: hidden` und die Ellipse in
            einem; der `title` macht den vollen Text verfügbar, wenn
            gekürzt wurde. Ein umgebrochener Wert hat die Karte höher
            gemacht als ihre Nachbarn — und seit das Raster alle Zeilen
            gleich hoch macht, hätte er **alle** Karten mitgezogen.
            Lange Texte gehören in die Zusatzzeile, nicht hierher. */}
        <p
          className="truncate text-2xl font-medium text-text-primary"
          title={typeof value === "string" ? value : undefined}
        >
          {error ? "—" : value}
        </p>
        {error ? (
          <p className="mt-0.5 text-xs text-warning">Wert nicht verfügbar</p>
        ) : subValue ? (
          <p className="mt-0.5 text-xs text-text-tertiary">{subValue}</p>
        ) : null}
        {!error && note ? (
          <p className="mt-0.5 text-[11px] leading-tight text-text-tertiary">
            {note}
          </p>
        ) : null}
      </div>
    </div>
  );
}
