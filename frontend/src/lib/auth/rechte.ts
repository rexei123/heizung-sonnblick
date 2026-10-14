/**
 * Wer darf was — eine Quelle für die Oberfläche (Sprint 21 A2).
 *
 * **Was diese Datei nicht ist: eine Zugangsbeschränkung.** Sie entscheidet,
 * ob ein Knopf *erscheint*. Abgewiesen wird serverseitig, und zwar auch
 * dann, wenn jemand den Knopf nie gesehen hat (CLAUDE.md §5.30). Eine
 * versteckte Schaltfläche ist Bedienung, keine Sicherheit.
 *
 * Der Zweck ist der Fehlertyp aus §5.77, eine Ebene höher: eine Handlung
 * anzubieten, die mit 403 endet, kostet beim nächsten Mal Vertrauen in die,
 * die funktioniert. Vor diesem Sprint sah ein Mitarbeiter „Zimmer löschen"
 * in Rot in der Kopfzeile und bekam nach dem Bestätigungsdialog eine
 * Fehlermeldung.
 *
 * **Jede Funktion nennt das Gate, das sie spiegelt.** Wer eines der Gates
 * ändert, findet über diese Datei die Oberfläche dazu — und umgekehrt. Ohne
 * die Fundstellen wäre das hier eine zweite Wahrheit, die beim ersten
 * Rollen-Umbau stumm auseinanderläuft (§5.53).
 *
 * `null` heißt „nicht eingeloggt" und ist in jeder Funktion `false`. Der
 * Normalfall ist das nicht — die Seiten liegen hinter der Anmeldung —, aber
 * während des ersten `/me` ist `user` kurz `null`, und ein Knopf, der dabei
 * aufblitzt, ist derselbe Fehler in Kleinformat.
 */

import type { User } from "@/lib/api/types";

/**
 * Wunschtemperatur setzen und aufheben.
 *
 * Gate: `require_mitarbeiter` an `POST /rooms/{id}/overrides`
 * (`api/v1/overrides.py:135`) und `DELETE .../overrides/{id}`
 * (`:232`) — Admin **und** Mitarbeiter.
 */
export function darfTemperaturAendern(user: User | null): boolean {
  return user !== null;
}

/**
 * Übersteuerungs-Sperre umschalten.
 *
 * Gate: `require_mitarbeiter` an
 * `PATCH /rooms/{id}/override-block-state` (`api/v1/rooms.py:220`).
 */
export function darfUebersteuerungSperren(user: User | null): boolean {
  return user !== null;
}

/**
 * Zimmer-Stammdaten ändern, inklusive Raumtyp und Löschen.
 *
 * Gate: `require_admin` an `PATCH /rooms/{id}` (`api/v1/rooms.py:162`)
 * und `DELETE /rooms/{id}` (`:312`).
 */
export function darfStammdatenAendern(user: User | null): boolean {
  return user?.role === "admin";
}

/**
 * Geräte einer Zone zuordnen, tauschen, lösen, stilllegen.
 *
 * Gate: `require_admin` an `DELETE /devices/{id}/heating-zone`
 * (`api/v1/devices.py:473`) und an allen Mutationen in
 * `api/v1/heating_zones.py` (`:157`, `:200`, `:247`).
 */
export function darfGeraeteVerwalten(user: User | null): boolean {
  return user?.role === "admin";
}
