/**
 * Der Text zu einem Fehler aus `apiClient` (Sprint 24e, PR B).
 *
 * **Der Befund, und er ist unangenehm.** Der Betreiber hat am 25.10.2026
 * gemeldet, das Speichern einer Betriebszeit habe „keine Bestätigung"
 * gebracht — und auch keinen Fehler. Die Ursache war nicht der Server
 * (geprüft: `PATCH /rooms/{id}/betriebszeit` antwortet für 07:00/22:00 mit
 * **200**), sondern die Anzeige:
 *
 * `apiClient` wirft ein **einfaches Objekt** `{status, detail, error_code}`
 * und keine `Error`-Instanz. Wer `fehler.message` liest, bekommt
 * `undefined` — und `setFehler(undefined)` rendert einen Kasten mit
 * nichts darin. Ein Fehler, der als leere Zeile erscheint, ist von „nichts
 * passiert" nicht zu unterscheiden.
 *
 * **Siebenmal dieselbe Zeile.** `betriebszeit-form`, `measure-only-toggle`,
 * `sollwert-wirksamkeit` und vier Stellen in `relay-card` haben alle
 * `fehler.message` gelesen, und zwar über drei Sprints hinweg — weil jede
 * Komponente ihre Fehlerbehandlung selbst geschrieben hat. Deshalb steht
 * sie jetzt einmal hier: die nächste Komponente erbt sie, statt sie neu zu
 * erfinden.
 *
 * `mapOverrideError` bleibt daneben bestehen und ist nicht dasselbe: es
 * übersetzt **bekannte** `error_code`-Werte der Übersteuerungs-Domäne in
 * Sätze für den Hotelier. Diese Funktion hier ist der Rückfall für alles
 * andere — sie zeigt, was der Server gesagt hat, und erfindet nichts.
 */

import type { ApiError } from "./types";

const UNBEKANNT = "Unbekannter Fehler — bitte die Seite neu laden.";

function istApiFehler(err: unknown): err is ApiError {
  return typeof err === "object" && err !== null && "status" in err && "detail" in err;
}

/**
 * Was dem Nutzer gezeigt wird. Nie leer — eine leere Fehlermeldung ist
 * schlimmer als eine ungenaue.
 */
export function fehlerText(err: unknown): string {
  if (istApiFehler(err)) {
    const d = err.detail;
    if (typeof d === "string" && d.trim() !== "") {
      return d;
    }
    // Pydantic antwortet mit einer Liste von Einzelfehlern; FastAPI mit
    // einem Objekt. Beides ist kein Satz, aber besser als nichts — und
    // der Status sagt, woran es lag.
    if (d !== undefined && d !== null) {
      return `${err.status}: ${JSON.stringify(d)}`;
    }
    return `Der Server hat mit ${err.status} abgewiesen.`;
  }
  if (err instanceof Error && err.message.trim() !== "") {
    return err.message;
  }
  return UNBEKANNT;
}
