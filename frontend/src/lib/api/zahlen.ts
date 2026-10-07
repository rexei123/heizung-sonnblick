/**
 * Zahlen-Normalisierung an der API-Grenze.
 *
 * **Der Anlass, 07.10.2026 15:00.** `/devices` war nach dem Deploy von
 * Sprint 20e nicht mehr benutzbar:
 *
 *     Application error: a client-side exception
 *     TypeError: a.toFixed is not a function
 *
 * `DeviceRead.valve_delta_k` ist im Backend ein `Decimal` und stand nicht im
 * `field_serializer`. Pydantic serialisiert ein `Decimal` ohne Eintrag als
 * JSON-**String** (`"5.40"`), der Typ hier sagt aber `number | null`, und
 * `formatDelta` rief `.toFixed()` darauf.
 *
 * Die Ursache ist im Backend behoben (das Feld steht jetzt im Serializer,
 * ein Test über die Feld-Annotationen hält es fest). **Diese Datei ist die
 * zweite Linie**, und sie ist nicht überflüssig:
 *
 * - Der TypeScript-Typ ist eine **Behauptung** über fremde Daten, keine
 *   Zusicherung. `apiClient.get<Device>` castet; zur Laufzeit prüft nichts.
 * - Der Fehler war nicht ein falscher Wert in einer Zelle, sondern ein
 *   **Absturz der ganzen Seite**. Diese Asymmetrie rechtfertigt eine
 *   Prüfung an der Grenze: eine Zahl, die als String kommt, soll eine
 *   normalisierte Zahl werden, kein Totalschaden.
 * - Dasselbe Risiko trägt jedes künftige `Decimal`-Feld. Eine Liste hier
 *   ist nicht schöner als ein Serializer dort, aber sie wirkt auch, wenn
 *   das Backend die Konvention verletzt.
 *
 * **Warum kein vollständiges Zod-Schema für `Device`.** Es hätte vierzig
 * Felder, von denen neununddreißig nichts mit dem Vorfall zu tun haben, und
 * es wäre unter Zeitdruck geschrieben worden — mit dem Risiko, dass ein
 * zu strenges Feld die Seite auf einem anderen Weg abschießt (`parse`
 * wirft). Was hier steht, berührt ausschließlich die Zahlenfelder und
 * lässt alles andere unangetastet. Ein echter Zod-Spiegel für `Device` ist
 * ein eigener Schnitt (Backlog), kein Hotfix.
 */

/**
 * Macht aus einem Zahlenfeld der API zuverlässig `number | null`.
 *
 * Akzeptiert absichtlich mehr, als der Typ verspricht: `number` (der
 * Normalfall), `string` (ein `Decimal` ohne Serializer), `null`/`undefined`
 * (Feld fehlt oder ist leer). Alles andere — Objekte, Arrays, `NaN`,
 * nicht-numerische Strings — wird `null`.
 *
 * `null` und nicht `0` für den unlesbaren Fall: eine 0 wäre eine Aussage.
 * Bei `valve_delta_k` stünde dann „Ist liegt 0,0 K über Soll" in einem
 * Hinweistext, und das ist falsch statt leer.
 */
export function zahlOderNull(wert: unknown): number | null {
  if (typeof wert === "number") {
    return Number.isFinite(wert) ? wert : null;
  }
  if (typeof wert === "string") {
    // Leerstring ist kein 0 — `Number("")` wäre 0, und das wäre eine
    // erfundene Messung.
    if (wert.trim() === "") return null;
    const n = Number(wert);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Normalisiert die genannten Felder eines API-Objekts an seiner Grenze.
 *
 * Arbeitet auf einer Kopie und lässt alle übrigen Felder unberührt — das
 * Objekt bleibt also das, was der Typ sagt, nur mit verlässlichen Zahlen in
 * den aufgezählten Feldern.
 */
export function zahlenfelderNormalisieren<T extends object>(
  objekt: T,
  felder: readonly (keyof T)[],
): T {
  const kopie = { ...objekt } as Record<string, unknown>;
  for (const feld of felder) {
    const name = feld as string;
    if (name in kopie) {
      kopie[name] = zahlOderNull(kopie[name]);
    }
  }
  return kopie as T;
}
