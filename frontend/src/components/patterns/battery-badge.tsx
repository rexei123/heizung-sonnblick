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
 *
 * Sprint 20 (AE-72): die Zahl ist die **Spannung in Volt**, nicht mehr ein
 * Prozentwert — und zwar der 24-h-Median, aus dem die Stufe entstanden ist
 * (``device.battery_voltage_median``). Nicht der letzte Frame: ein einzelner
 * Messwert kann unter Motorlast einbrechen, dann widerspricht der Badge sich
 * selbst.
 *
 * Sprint 20b (AE-73): die Labels sagten, was zu TUN ist, nicht wie der
 * Zustand heißt — „Beobachten" statt „Batterie schwach", „Tauschen" statt
 * „Batterie kritisch". Grund: der Hotelier liest den Badge im Vorbeigehen
 * und muss daraus eine Handlung ableiten.
 *
 * **Teilweise zurückgenommen am 08.10.2026 — und zwar auf eigenen Wunsch
 * des Hoteliers, nicht als Korrektur eines Fehlers.** Das Prinzip aus AE-73
 * („das Label sagt die Handlung") steht und fällt damit, dass die Handlung
 * stimmt. Bei `kritisch` stimmte sie nicht: „Tauschen" ist ein Auftrag, und
 * die Betriebsregel lautet anders.
 *
 * **Die Betriebsregel: getauscht wird bei drei Stunden Funkstille, nicht
 * bei einer Spannung.** Die Spannung ist Information, kein Auftrag.
 *
 * Der Befund dahinter, Gerät 102: 2,6 V am 04.10. war ein **gehaltener
 * Einzelwert unter Last**, kein Lebensende. `fCnt` lief lückenlos weiter,
 * und seit dem 06.10. meldet das Gerät wieder 3,5 V. Ein Tausch wäre
 * unnötig gewesen.
 *
 * Das ist unangenehm, weil der 24-h-Median genau solche Einbrüche abfangen
 * soll (AE-72) — und bei einem Einbruch, der **über Stunden** anhält, kann
 * er es nicht. Die Stufe ist deshalb schwächer, als ihr Name versprach, und
 * das Etikett sagt es nun.
 *
 * Deshalb: `kritisch` heißt „Batterie niedrig", `warn` heißt „Batterie
 * schwach". Beides Zustände. Die Handlung steht im Hinweistext und nennt die
 * Bedingung, unter der sie gilt.
 *
 * Farben und Zustände sind unverändert — es ist eine Wortänderung, keine
 * neue Achse. **Wer sie zurückdreht, muss die Betriebsregel mit ändern**
 * (§5.77: ein überholter Vermerk wird wie ein Befund gelesen).
 *
 * Die Hints nennen **keine Schwellenwerte** mehr (die Spec-Untergrenze von
 * 2,7 V ist mit dem Etikett-Wechsel ebenfalls entfallen — sie legte eine
 * Handlung nahe, die es nicht gibt). Die Grenzen stehen seit
 * AE-73 in den Settings und sind pro Haus verstellbar; eine Zahl im Text
 * wäre eine zweite Wahrheit, die beim ersten Nachjustieren still falsch
 * wird (§5.77). Was dort steht, sind Eigenschaften der Hardware (die
 * Spec-Untergrenze von 2,7 V) — die ändert keine Konfiguration.
 *
 * **Nachbesserung 30.09.2026 (Befund heizung-test).** Auf der Geraeteliste
 * stand reihenweise „Batterie unbekannt" ohne Zahl. Das ist fuer den
 * Hotelier wertlos — er weiss danach so viel wie vorher, und „unbekannt"
 * liest sich wie ein Defekt, obwohl die Zelle voll sein kann.
 *
 * Der Grund: eine Stufe braucht drei Messwerte in 24 Stunden
 * (``BATTERY_MIN_SAMPLES``), und ``battery_voltage`` gibt es erst seit
 * Migration 0024. Ein Geraet mit einem oder zwei Werten hatte also eine
 * bekannte Spannung und trotzdem keine Stufe.
 *
 * Seither gilt: **nie ein Badge ohne Spannung, wenn irgendeine Spannung
 * bekannt ist.** „unbekannt" ohne Zahl bleibt fuer den einen Fall, in dem es
 * zutrifft — es wurde nie eine gemeldet.
 *
 * - ``compact``: Pille (Icon + Label), Tooltip als ``title``.
 * - ``detailed``: Pille plus erklaerende Hint-Zeile.
 *
 * Wording §5.20: „Thermostat"/„Batterie", kein „Vicki".
 */

import type { BatteryHealthState } from "@/lib/api/types";
import { formatAgeShort, formatDateTime, formatVolts } from "@/lib/format";

type Variant = "compact" | "detailed";

interface BatteryBadgeProps {
  batteryState: BatteryHealthState;
  /** 24-h-Median der Spannung in Volt — die Zahl, die zur Stufe gehört. */
  batteryVolts?: number | null;
  /**
   * ISO-Zeitstempel, wenn im Fenster ein Batteriewechsel erkannt wurde
   * (`device.battery_jump_at`). Erklärt ein „unbekannt", das keins ist:
   * nach einem Wechsel zählt nur das Fenster ab dem Sprung, und bis drei
   * Messwerte darin sind, gibt es keinen belastbaren Median.
   */
  batteryJumpAt?: string | null;
  /**
   * Letzter bekannter Spannungswert (`device.battery_last_voltage`) und sein
   * Zeitpunkt (`device.battery_last_at`) — unabhängig davon, ob eine Stufe
   * zustande kam.
   *
   * Ohne diese beiden zeigt der Badge „Batterie unbekannt" ohne Zahl, und
   * das ist keine Auskunft. Mit ihnen steht dort „3,5 V · vor 2 h": die
   * Zelle ist voll, das Gerät schweigt seit zwei Stunden — zwei
   * Informationen statt keiner.
   */
  batteryLastVolts?: number | null;
  batteryLastAt?: string | null;
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
    hint: "Spannung niedrig. Das Gerät regelt weiter; getauscht wird bei Funkstille.",
  },
  kritisch: {
    label: "Batterie niedrig",
    icon: "battery_alert",
    badgeClass: "bg-danger-soft text-danger",
    hint:
      "Spannung niedrig — zur Kenntnis, nicht als Auftrag. Getauscht wird, " +
      "wenn sich das Gerät drei Stunden nicht meldet.",
  },
  unbekannt: {
    label: "Batterie unbekannt",
    icon: "battery_unknown",
    badgeClass: "bg-surface-alt text-text-tertiary",
    hint: "Noch zu wenige Messwerte für eine Aussage.",
  },
};

/** Hinweis nach einem erkannten Batteriewechsel (ersetzt den Hint). */
const HINT_NACH_WECHSEL = "Batteriewechsel erkannt — Messwerte sammeln sich.";

/**
 * Wert bekannt, Stufe nicht. Sagt, was fehlt, statt „unbekannt" zu sagen:
 * für eine Stufe braucht es drei Messwerte in 24 Stunden.
 */
const HINT_OHNE_STUFE = "Letzter Messwert — für eine Stufe fehlen Messwerte.";

/** Der einzige Fall, in dem „unbekannt" ohne Zahl richtig ist. */
const HINT_NIE_GEMELDET = "Dieses Gerät hat noch nie eine Spannung gemeldet.";

export function BatteryBadge({
  batteryState,
  batteryVolts = null,
  batteryJumpAt = null,
  batteryLastVolts = null,
  batteryLastAt = null,
  variant = "compact",
  className,
}: BatteryBadgeProps) {
  // Defensive: unbekannter/fehlender State (z. B. Altdaten) -> "unbekannt"
  // statt Crash (S5). Backend garantiert das Feld, Mocks evtl. nicht.
  const cfg = CONFIG[batteryState] ?? CONFIG.unbekannt;

  // ------------------------------------------------------------------
  // Was in der Pille steht (Befund heizung-test 30.09.2026)
  // ------------------------------------------------------------------
  //
  // **Nie ein Badge ohne Spannung, wenn irgendeine Spannung bekannt ist.**
  // „Batterie unbekannt" ohne Zahl ist für den Hotelier wertlos — er weiß
  // danach so viel wie vorher. Vier Fälle, in dieser Reihenfolge:
  //
  // | Lage | Pille | Farbe |
  // |---|---|---|
  // | Stufe berechenbar | „Batterie OK · 3,1 V" / „Batterie niedrig · 2,5 V" | grün/gelb/rot |
  // | Wechsel erkannt | „Batteriewechsel erkannt · 3,5 V" | grau |
  // | keine Stufe, Wert bekannt | „3,5 V · vor 2 h" | grau |
  // | nie eine Spannung gemeldet | „Batterie unbekannt" | grau |
  //
  // Bei vorhandener Stufe ist die Zahl der **Median**, nicht der letzte
  // Frame — sonst widerspricht der Badge sich selbst, sobald ein einzelner
  // Wert unter Motorlast einbricht. Ohne Stufe ist es umgekehrt der letzte
  // Wert samt Alter: er ist keine Stufe, aber eine Auskunft, und das Alter
  // sagt, wie viel sie noch wert ist.
  const hatStufe = batteryState !== "unbekannt";
  const zeigeMedian = hatStufe && batteryVolts != null;

  let label: string;
  let hint: string;
  if (zeigeMedian) {
    label = `${cfg.label} · ${formatVolts(batteryVolts)}`;
    hint = cfg.hint;
  } else if (batteryJumpAt != null && batteryLastVolts != null) {
    label = `Batteriewechsel erkannt · ${formatVolts(batteryLastVolts)}`;
    hint = HINT_NACH_WECHSEL;
  } else if (batteryLastVolts != null) {
    label = `${formatVolts(batteryLastVolts)} · ${formatAgeShort(batteryLastAt)}`;
    hint = HINT_OHNE_STUFE;
  } else {
    label = cfg.label;
    hint = hatStufe ? cfg.hint : HINT_NIE_GEMELDET;
  }

  // Der Zeitstempel im Tooltip haengt am WERT, nicht an sich selbst: ein
  // Zeitpunkt ohne Spannung ist keine Auskunft, sondern eine Zahl neben der
  // Aussage „hat noch nie eine Spannung gemeldet" — ein Widerspruch. Ein
  // e2e-Test hat genau das gefunden.
  const title = zeigeMedian
    ? `${formatVolts(batteryVolts)} — Median der letzten 24 Stunden. ${cfg.hint}`
    : batteryLastVolts != null && batteryLastAt != null
      ? `Letzter Messwert: ${formatDateTime(batteryLastAt)}. ${hint}`
      : hint;

  const pill = (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium w-fit ${cfg.badgeClass}`}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {cfg.icon}
      </span>
      {label}
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
        <span className="text-xs text-text-tertiary">{hint}</span>
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
      {label}
    </span>
  );
}
