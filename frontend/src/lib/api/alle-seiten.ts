/**
 * Eine Liste über alle Seiten holen — der Schleifen-Code aus Sprint 20c,
 * einmal statt dreimal.
 *
 * Sprint 20c hat `devicesApi.list` auf Client-Paginierung umgestellt
 * (B-20c-1: die Oberfläche zeigte 100 von 104 Geräten, ohne das zu sagen).
 * Sprint 20d braucht dasselbe für Zimmer und Raumtypen (B-20c-2) — und
 * damit stand die Wahl zwischen drei Kopien derselben Schleife oder einer
 * Stelle.
 *
 * **Drei Kopien wären genau der Befund, den der Brief zu 20d eine Ebene
 * höher beschreibt:** vier Aufrufer desselben Endpoints hatten drei
 * verschiedene `limit`-Werte, weil jeder für sich entschieden hat. Eine
 * kopierte Schleife driftet genauso — die erste Zeile, die jemand in einer
 * der drei Dateien anpasst, gilt dann für ein Drittel der Listen.
 *
 * Was hier **nicht** hingehört: echte Paginierung. Belegungen wachsen
 * unbegrenzt und werden seitenweise geladen, mit Gesamtzahl und einem Knopf
 * in der Oberfläche (`occupanciesApi.list`, Sprint 20d Entscheidung B). Wer
 * das mit dieser Funktion bauen will, baut den Befund von 20c nach.
 */

/**
 * Seitengröße. **100 — dieselbe Zahl wie der Server-Default** aller drei
 * Endpoints (`api/v1/devices.py:247`, `api/v1/rooms.py:97`,
 * `api/v1/room_types.py:80`).
 *
 * Die naheliegende Wahl wäre eine Seite, die so groß ist, dass sie den
 * ganzen Bestand trägt (etwa 500 bei 104 Vickis) — ein Aufruf, Schleife nur
 * als Absicherung. Verworfen: dann läuft die Schleife im Betrieb **nie**,
 * und eine Paginierung, die nur im Test greift, ist genau die Sorte Code,
 * die beim Wachsen des Bestands das erste Mal scharf wird. Bei 100 sind es
 * bei den Geräten heute zwei Aufrufe, und der zweite Durchlauf ist belegt —
 * jeden Tag.
 */
export const SEITE = 100;

/**
 * Sicherheitsnetz gegen eine Endlosschleife. Greift nur, wenn das Backend
 * eine volle Seite zurückgibt, obwohl keine weiteren Daten da sind — also
 * bei einem Fehler, nicht bei großen Beständen: 100 × 100 = 10 000 Zeilen,
 * das Hundertfache des Geräte-Bestands und mehr als das Zweihundertfache
 * des Zimmer-Bestands.
 */
export const MAX_SEITEN = 100;

/**
 * Holt so viele Seiten, wie es braucht, und **wirft**, statt abzuschneiden.
 *
 * Der Aufrufer liefert eine Funktion, die **eine** Seite holt. Dass die
 * Paginierung verlässlich ist, hängt an einer Eigenschaft des Endpoints,
 * nicht an dieser Schleife: die Sortierung muss **serverseitig** und auf
 * einem **eindeutigen** Schlüssel liegen. Sonst kann zwischen zwei Seiten
 * eine Zeile doppelt erscheinen und eine andere gar nicht. Für die drei
 * Aufrufer ist das belegt:
 *
 * | Endpoint | Sortierung | eindeutig |
 * |---|---|---|
 * | `/devices` | `id` | ✅ |
 * | `/room-types` | `id` | ✅ |
 * | `/rooms` | `floor`, numerischer Präfix, `number` | ✅ — `Room.number` ist `unique` |
 *
 * @param holeSeite holt eine Seite; bekommt `limit` und `offset`.
 * @param was Bezeichnung für die Fehlermeldung, z. B. "Geräteliste".
 */
export async function alleSeiten<T>(
  holeSeite: (limit: number, offset: number) => Promise<T[]>,
  was: string,
): Promise<T[]> {
  const alle: T[] = [];
  for (let seite = 0; seite < MAX_SEITEN; seite += 1) {
    const teil = await holeSeite(SEITE, seite * SEITE);
    alle.push(...teil);
    // Kürzere Seite als angefragt = letzte Seite. Bei genau SEITE Treffern
    // folgt noch ein Aufruf, der leer zurückkommt — ein Roundtrip mehr,
    // dafür keine Annahme darüber, wie viele es insgesamt sind.
    if (teil.length < SEITE) return alle;
  }
  throw new Error(
    `${was} nicht vollständig geladen: mehr als ${MAX_SEITEN * SEITE} ` +
      "Einträge oder das Backend liefert dauerhaft volle Seiten. " +
      "Die Liste wird NICHT angezeigt, weil sie unvollständig wäre.",
  );
}
