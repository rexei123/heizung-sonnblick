/**
 * Warum eine Übersteuerung beendet wurde (Sprint 23 T1.7).
 *
 * **Der Fehler, den diese Datei behebt.** Die Historie ordnete den Grund
 * über ein Textmuster zu:
 *
 * ```ts
 * if (grund.startsWith("auto")) { … } else { "manuell aufgehoben" }
 * ```
 *
 * Zwei von fünf Werten fallen durch dieses Muster, weil sie nicht mit
 * `auto` beginnen — und beide sind **automatische** Vorgänge:
 *
 * * `superseded` — von einer neueren Drehung derselben Zone verdrängt,
 * * `room_override_blocked` — ein Mitarbeiter hat das Zimmer gesperrt.
 *
 * Beide erschienen als „manuell aufgehoben". In der Historie von Zimmer
 * 306 (21./22.10.2026, **zwölf Drehungen in sechzehn Stunden**) steht
 * damit elfmal eine falsche Tatsachenbehauptung: niemand hat dort etwas
 * von Hand aufgehoben.
 *
 * **Der Fehler war das Muster, nicht einer seiner Zweige.** Deshalb eine
 * Tabelle mit **genauen** Schlüsseln. Ein Präfix-Vergleich lädt den
 * nächsten Fall derselben Art ein.
 *
 * **Unbekanntes wird als Rohwert gezeigt.** Vorgabe des Betreibers, und
 * sie ist richtig: ein unbekannter Wert ist entweder ein neuer Code aus
 * dem Backend oder ein Freitext, den ein Mitarbeiter beim Aufheben
 * eingegeben hat. Im ersten Fall wäre „manuell aufgehoben" eine falsche
 * Tatsachenbehauptung, im zweiten ist der Rohwert genau das, was dort
 * steht. Beides ist mit dem Rohwert richtig bedient.
 *
 * Ein Spiegel-Test (`backend/tests/test_aufhebungsgrund_spiegel.py`)
 * hält die Schlüssel gegen die Konstanten im Backend.
 */

/**
 * Genaue Schlüssel → Text. Die Werte stehen im Backend als Konstanten
 * (`override_service.REVOKE_REASON_*`, `override_pms_hook`) — wer einen
 * umbenennt, bringt den Spiegel-Test zum Fallen.
 */
export const AUFHEBUNGSGRUND: Record<string, string> = {
  superseded: "ersetzt (neue Drehung)",
  auto_revoke_on_checkout: "mit der Abreise beendet",
  room_override_blocked: "durch Sperre beendet",
  "auto: expired": "abgelaufen",
};

/**
 * Der Text zu einem `revoked_reason`.
 *
 * `null` oder leer heißt „über die Oberfläche aufgehoben, ohne Grund" —
 * dort ist das Feld freiwillig. Alles andere, was nicht in der Tabelle
 * steht, kommt **unverändert** zurück.
 */
export function aufhebungsgrundText(grund: string | null | undefined): string {
  if (grund === null || grund === undefined || grund.trim() === "") {
    return "manuell aufgehoben";
  }
  return AUFHEBUNGSGRUND[grund] ?? grund;
}
