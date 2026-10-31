/**
 * Der Gerätetyp als Wort (Entscheidung Betreiber, 31.10.2026).
 *
 * **Warum er sichtbar sein muss.** Bis zur Nachlieferung bestand das Haus
 * aus 104 Thermostaten; der Typ war keine Frage, weil es nur eine Antwort
 * gab. Mit den beiden Relais (108, 109) stehen zwei Geräte in derselben
 * Liste, die nichts messen und ein Ventil nicht kennen — und sie sehen
 * dort aus wie jedes andere. Wer bei einem Relais nach einer
 * Ventilstellung sucht, sucht etwas, das es nie geben wird.
 *
 * Dasselbe Argument hat Sprint 24c für den `FuehlerBadge` gebraucht. Der
 * Unterschied: dort ist es eine **Rolle** (ein Thermostat, das nur
 * misst), hier ist es die **Art** der Hardware. Beide stehen
 * nebeneinander und widersprechen sich nicht — ein Fühler ist ein
 * Thermostat in einer besonderen Rolle.
 *
 * **Jedes Gerät nennt seinen Typ, auch das Thermostat.** Nur das Relais
 * zu kennzeichnen wäre billiger und würde die Frage beantworten, solange
 * jemand die Regel kennt („ohne Marke ist es ein Thermostat"). Eine
 * Information, die aus dem **Fehlen** einer Marke gelesen werden muss,
 * ist genau die Falle aus Paragraph 5.57 — nur eine Ebene höher. Der
 * Betreiber hat „Thermostat/Relais sichtbar" verlangt, nicht „Relais
 * erkennbar".
 *
 * **Leise, nicht laut.** Der Typ steht als Zeile unter der Bezeichnung
 * und nicht als gefärbte Pille: in 104 von 106 Zeilen sagt er
 * „Thermostat", und was fast immer dasselbe sagt, darf nicht um
 * Aufmerksamkeit rufen. Dieselbe Form wie der Zweitname in der
 * Zimmerübersicht.
 */

import type { Device } from "@/lib/api/types";

/** Das Wort zum Enum-Wert. Eine Stelle, damit die Liste und die
 *  Geräteseite nicht zwei Vokabulare bekommen (Paragraph 5.53). */
export function geraetetypText(kind: Device["kind"]): string {
  if (kind === "relay") {
    return "Relais";
  }
  if (kind === "sensor") {
    return "Sensor";
  }
  return "Thermostat";
}

/** Das Material-Symbol zum Typ. Kein Emoji — es rendert je Betriebssystem
 *  anders und trägt keine Barrierefreiheits-Bedeutung. */
export function geraetetypIcon(kind: Device["kind"]): string {
  if (kind === "relay") {
    return "toggle_on";
  }
  if (kind === "sensor") {
    return "sensors";
  }
  return "thermostat";
}

export function Geraetetyp({
  kind,
  className,
}: {
  kind: Device["kind"];
  className?: string;
}) {
  const text = geraetetypText(kind);
  return (
    <span
      data-testid="geraetetyp"
      data-kind={kind}
      className={`inline-flex items-center gap-1 text-text-tertiary text-xs ${className ?? ""}`}
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
        {geraetetypIcon(kind)}
      </span>
      {text}
    </span>
  );
}
