"use client";

/**
 * ValveHintBadge (Sprint 20e, T7/T10 — Regel 3 und 3b).
 *
 * **Warum dieser Badge existiert, und warum er nicht optional ist.**
 *
 * Bis Sprint 20e war Engine-Layer 4 der Melder für ein abgenommenes Gerät:
 * alle Thermostate eines Zimmers melden „nicht aufgesetzt" → Frostschutz.
 * Dieser Melder hat im Haus nicht funktioniert, und 20e hat ihn für Geräte
 * mit Montage-Nachweis stillgelegt — also für genau die Geräte, bei denen er
 * hätte anschlagen sollen. Ein montiertes Gerät, das später tatsächlich
 * abfällt, erkennt die Engine nicht mehr.
 *
 * Dieser Badge ist der Ersatz, und er misst die **Wirkung** statt der
 * Mechanik (§5.76): ein Ventil ohne Kopf steht voll offen, das Zimmer wird
 * also **heiß**, nicht kalt. Das ist ohne den Backplate-Taster messbar.
 *
 * Quelle ist ``device.valve_state`` aus dem Device-Response — kein eigener
 * API-Call, prop-getrieben wie ``BatteryBadge``. Das Urteil kommt vollständig
 * aus dem Backend (``services/valve_health.py``); das Frontend baut **keine**
 * Schwellen nach. Die Grenzen stehen in den Settings und sind pro Haus
 * verstellbar — eine Zahl im Text wäre eine zweite Wahrheit, die beim ersten
 * Nachjustieren still falsch wird (§5.77).
 *
 * Vier Zustände:
 *
 * | ``valve_state``     | Anzeige | Farbe |
 * |---|---|---|
 * | ``ok``              | nichts  | — |
 * | ``ventil_klemmt_zu``| Ventil prüfen | gelb |
 * | ``zimmer_zu_warm``  | Zimmer zu warm | rot |
 * | ``unbekannt``       | nichts  | — |
 *
 * **``ok`` und ``unbekannt`` rendern nichts.** Das ist der Unterschied zum
 * BatteryBadge, und er ist beabsichtigt: die Batterie-Achse hat für jedes
 * Gerät eine Aussage, dieser Badge ist ein **Hinweis**. Eine Pille „Ventil
 * in Ordnung" an 104 Zeilen wäre Rauschen, in dem die zwei auffälligen
 * Zeilen untergehen — und genau das soll der Hinweis verhindern.
 *
 * Dass ``unbekannt`` ebenfalls nichts rendert, ist dagegen ein Kompromiss
 * und kein Urteil: „zu wenige Messwerte" ist eine echte Information, aber
 * sie gehört auf die Offline-Achse (``health_state``), die daneben schon
 * steht. Zwei Badges für dieselbe Ursache wären zwei Melder für ein
 * Problem.
 *
 * **Rot für „Zimmer zu warm", gelb für „Ventil prüfen".** Die Farbe folgt
 * dem Schaden, nicht der Dringlichkeit des Handgriffs: ein geschlossenes
 * Ventil kostet Komfort in einem Zimmer, ein offenes Ventil ohne Kopf heizt
 * gegen das Fenster und kostet Energie, solange es niemand sieht.
 */

import type { ValveState } from "@/lib/api/types";

type Variant = "compact" | "detailed";

interface ValveHintBadgeProps {
  valveState: ValveState;
  /**
   * Gemessener Abstand in Kelvin, der zum Urteil gehört
   * (``device.valve_delta_k``) — der **knappste** Wert des Fensters, nicht
   * der Spitzenwert. Er sagt, wie weit die Lage von der Schwelle weg ist;
   * ein Spitzenwert würde den Befund dramatischer darstellen, als er ist.
   */
  valveDeltaK?: number | null;
  variant?: Variant;
}

interface HintConfig {
  label: string;
  icon: string;
  badgeClass: string;
  hint: (delta: string | null) => string;
}

const CONFIG: Record<"ventil_klemmt_zu" | "zimmer_zu_warm", HintConfig> = {
  ventil_klemmt_zu: {
    label: "Ventil prüfen",
    icon: "build",
    badgeClass: "bg-warning-soft text-warning",
    // Beide Ursachen werden genannt, statt zu raten: eine gemeldete
    // Ventilstellung von 0 % heißt entweder „zu" oder „nicht kalibriert",
    // und das ist aus den Daten nicht zu unterscheiden. Beide verdienen
    // denselben Handgriff.
    hint: (delta) =>
      `Soll liegt${delta ? ` ${delta}` : ""} über Ist, Ventil meldet trotzdem zu. ` +
      `Ventil klemmt oder ist nicht kalibriert.`,
  },
  zimmer_zu_warm: {
    label: "Zimmer zu warm",
    icon: "local_fire_department",
    badgeClass: "bg-danger-soft text-danger",
    // Der Satz nennt den Hauptverdacht zuerst, weil er der teuerste ist.
    hint: (delta) =>
      `Ist liegt${delta ? ` ${delta}` : ""} über Soll. ` +
      `Thermostatkopf abgenommen (Ventil steht dann offen) oder Ventil klemmt offen.`,
  },
};

function formatDelta(k: number | null | undefined): string | null {
  if (k === null || k === undefined) return null;
  // Eine Dezimalstelle: die Messgröße ist Numeric(5,2), aber 0,1 K ist die
  // Auflösung, in der über Raumtemperaturen gesprochen wird.
  return `${k.toFixed(1).replace(".", ",")} K`;
}

export function ValveHintBadge({
  valveState,
  valveDeltaK,
  variant = "compact",
}: ValveHintBadgeProps) {
  // Positiv formuliert statt als Ausschlussliste, und das ist nicht Kosmetik:
  // ein Wert, den dieser Badge nicht kennt — ein neuer Zustand aus dem
  // Backend, ein veralteter Mock, eine Antwort ohne das Feld — darf die
  // Geräteliste nicht zum Absturz bringen. Mit `CONFIG[valveState]` auf einem
  // unbekannten Schlüssel wäre `config` undefined und `config.hint` ein
  // Fehler, der die ganze Zeile mitnimmt.
  //
  // Aufgefallen in CI: fünf Bestands-Specs bauen Geräte-Mocks ohne
  // `valve_state`, und die Ausschlussliste ließ `undefined` durch. Das war
  // mein Fehler im Badge, nicht in den Mocks — ein Hinweis-Badge, der eine
  // Liste von 104 Zeilen abschießen kann, ist falsch gebaut.
  const config = valveState in CONFIG ? CONFIG[valveState as keyof typeof CONFIG] : undefined;
  if (config === undefined) {
    return null;
  }
  const hint = config.hint(formatDelta(valveDeltaK));

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
      <div className="flex flex-col gap-0.5" role="status" data-testid="valve-hint">
        {pill}
        <span className="text-xs text-text-tertiary">{hint}</span>
      </div>
    );
  }

  return (
    <span role="status" title={hint} data-testid="valve-hint">
      {pill}
    </span>
  );
}
