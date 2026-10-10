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

import type { ValveReferenz, ValveState } from "@/lib/api/types";

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
  /**
   * Worauf das relative Urteil von Regel 3b fußt (Sprint 20e-b) — plus der
   * Median der Referenzmenge und der Abstand dazu.
   *
   * **Warum der Hinweistext das nennen muss.** Bis 20e-b stand dort nur
   * „Ist liegt 6,0 K über Soll". Am 07.10.2026 traf das auf 14 Geräte zu,
   * echt waren zwei: leere Zimmer standen bei Herbstwetter ohne Heizung
   * über ihrem Sollwert. Der Satz war wahr und nutzlos. Mit dem zweiten
   * Abstand steht daneben, dass es nicht am Wetter liegt — und mit der
   * Referenz, womit verglichen wurde.
   */
  valveReferenz?: ValveReferenz | null;
  valveReferenzMedianC?: number | null;
  valveReferenzDeltaK?: number | null;
  variant?: Variant;
}

/** Was der Hinweistext zur Verfügung hat. */
interface HintDaten {
  /** Abstand zum Sollwert, formatiert („6,0 K") oder `null`. */
  delta: string | null;
  /** Abstand zur Referenzmenge, formatiert, oder `null`. */
  refDelta: string | null;
  /** Die Referenzmenge, in Worten („vergleichbaren Zimmern") oder `null`. */
  refName: string | null;
  /** Median der Referenzmenge („20,0 °C") oder `null`. */
  refMedian: string | null;
}

interface HintConfig {
  label: string;
  icon: string;
  badgeClass: string;
  hint: (daten: HintDaten) => string;
}

/**
 * Die Referenzmenge in Worten.
 *
 * `unbelegt` heißt „vergleichbare Zimmer", weil genau das die fachliche
 * Aussage ist: nicht belegte Zimmer sind thermisch dieselbe Population.
 * Bei `alle` steht „allen Zimmern" — der Rückfall vergleicht auch gegen
 * belegte, in denen Gäste 22–24 °C einstellen, und der Satz soll nicht
 * mehr Genauigkeit behaupten, als er hat.
 *
 * `keine` ergibt `null`: dann gibt es kein relatives Urteil, und ein Satz
 * über eine Referenz, die es nicht gab, wäre eine Erfindung.
 */
const REFERENZ_WORT: Record<ValveReferenz, string | null> = {
  unbelegt: "vergleichbaren Zimmern",
  alle: "allen Zimmern",
  keine: null,
};

const CONFIG: Record<"ventil_klemmt_zu" | "zimmer_zu_warm", HintConfig> = {
  ventil_klemmt_zu: {
    label: "Ventil prüfen",
    icon: "build",
    badgeClass: "bg-warning-soft text-warning",
    // Beide Ursachen werden genannt, statt zu raten: eine gemeldete
    // Ventilstellung von 0 % heißt entweder „zu" oder „nicht kalibriert",
    // und das ist aus den Daten nicht zu unterscheiden. Beide verdienen
    // denselben Handgriff.
    hint: ({ delta }) =>
      `Soll liegt${delta ? ` ${delta}` : ""} über Ist, Ventil meldet trotzdem zu. ` +
      `Ventil klemmt oder ist nicht kalibriert.`,
  },
  zimmer_zu_warm: {
    label: "Zimmer zu warm",
    icon: "local_fire_department",
    badgeClass: "bg-danger-soft text-danger",
    // Der Satz nennt zuerst die beiden Abstände und dann den Hauptverdacht,
    // weil der zweite Abstand das Wetter ausschließt — ohne ihn klingt
    // „6,0 K über Soll" im Oktober nach Herbstsonne.
    hint: ({ delta, refDelta, refName, refMedian }) => {
      const abstaende =
        refDelta && refName
          ? `Ist liegt${delta ? ` ${delta}` : ""} über Soll und ${refDelta} über ` +
            `${refName}${refMedian ? ` (Median ${refMedian})` : ""}.`
          : `Ist liegt${delta ? ` ${delta}` : ""} über Soll.`;
      return (
        `${abstaende} ` +
        `Thermostatkopf abgenommen (Ventil steht dann offen) oder Ventil klemmt offen.`
      );
    },
  },
};

/**
 * Formatiert den Abstand, und zwar **total**: kein Eingabewert kann werfen.
 *
 * Die erste Fassung war `k.toFixed(1)` mit einer Prüfung auf
 * `null`/`undefined`. Das hat am 07.10.2026 `/devices` abgeschossen: das
 * Backend sendete das `Decimal`-Feld als JSON-String (`"5.40"`), `.toFixed`
 * existiert auf einem String nicht, und `TypeError: a.toFixed is not a
 * function` nahm die ganze Seite mit.
 *
 * Der Typ sagt `number | null` — aber ein Typ ist eine Behauptung über
 * fremde Daten, keine Zusicherung. Die Prüfung geht deshalb auf
 * `typeof === "number"` statt auf die Abwesenheit von `null`: so ist nicht
 * nur der eine bekannte Fall abgedeckt, sondern jeder, in dem hier etwas
 * anderes als eine Zahl ankommt.
 *
 * Dieselbe Umkehrung wie bei der Zustandsprüfung unten (positiv formulieren
 * statt Ausschlussliste) und aus demselben Grund: ein Hinweis-Badge darf
 * eine Liste von 104 Zeilen nicht zerstören.
 */
function formatDelta(k: unknown): string | null {
  if (typeof k !== "number" || !Number.isFinite(k)) return null;
  // Eine Dezimalstelle: die Messgröße ist Numeric(5,2), aber 0,1 K ist die
  // Auflösung, in der über Raumtemperaturen gesprochen wird.
  return `${k.toFixed(1).replace(".", ",")} K`;
}

/**
 * Formatiert den Median als Temperatur, mit derselben Totalität wie
 * `formatDelta` und aus demselben Grund (§5.3-Familie: ein Typ ist eine
 * Behauptung über fremde Daten, keine Zusicherung).
 */
function formatMedian(c: unknown): string | null {
  if (typeof c !== "number" || !Number.isFinite(c)) return null;
  return `${c.toFixed(1).replace(".", ",")} °C`;
}

export function ValveHintBadge({
  valveState,
  valveDeltaK,
  valveReferenz,
  valveReferenzMedianC,
  valveReferenzDeltaK,
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
  // `valveReferenz` kommt aus fremden Daten und kann ein Wert sein, den
  // diese Fassung nicht kennt (neuer Zustand im Backend, veralteter Mock).
  // Positiv geprüft wie der Zustand oben: ein unbekannter Schlüssel ergibt
  // `undefined` und damit keinen Referenz-Satz, nicht einen Absturz.
  const refName =
    valveReferenz != null && valveReferenz in REFERENZ_WORT
      ? REFERENZ_WORT[valveReferenz]
      : null;
  const hint = config.hint({
    delta: formatDelta(valveDeltaK),
    refDelta: formatDelta(valveReferenzDeltaK),
    refName,
    refMedian: formatMedian(valveReferenzMedianC),
  });

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
