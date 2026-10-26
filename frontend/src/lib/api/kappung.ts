/**
 * Der Text zu einem Sollwert, der gekappt wird (Sprint 23 T1.7).
 *
 * **Der Befund.** Die Historie von Zimmer 306 zeigte am 21./22.10.2026
 * „30 °C, aktiv" — wirksam waren 25. Der Gastwunsch steht am Override,
 * gekappt wird in Layer 5 gegen die Grenzen des Raumtyps, und die Anzeige
 * las nur den ungekappten Wert. Sie behauptete damit eine Wirkung, die es
 * nicht gibt, und zwar zwölf Mal in sechzehn Stunden.
 *
 * Mit dem Rad an der Obergrenze (T1) entsteht dieser Fall seltener — aber
 * nicht nie: die Grenze gilt nur für das Rad, die Rezeption kann über die
 * Oberfläche weiterhin mehr eintragen, und Bestandszeilen bleiben.
 *
 * **Nur für aktive Zeilen.** Das Backend liefert `wirksam_gekappt_c` nur
 * dort; eine abgelaufene Zeile gegen die *heutigen* Grenzen zu rechnen
 * würde eine Vergangenheit behaupten, die so nicht war.
 */

/**
 * `"25 °C"` ohne Kappung, `"30 °C → begrenzt auf 25 °C"` mit.
 *
 * @param wunsch der eingetragene Wert (Gast oder Rezeption).
 * @param gekappt der wirksame Wert, oder `null`/`undefined` ohne Kappung.
 */
export function sollwertText(
  wunsch: number,
  gekappt: number | null | undefined,
): string {
  const gerundet = Math.round(wunsch);
  if (gekappt === null || gekappt === undefined || gekappt === gerundet) {
    return `${gerundet} °C`;
  }
  return `${gerundet} °C → begrenzt auf ${gekappt} °C`;
}

/** Wird hier gekappt? Für Stellen, die die beiden Teile selbst setzen. */
export function wirdGekappt(
  wunsch: number,
  gekappt: number | null | undefined,
): boolean {
  return (
    gekappt !== null && gekappt !== undefined && gekappt !== Math.round(wunsch)
  );
}
