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
 * Stammdaten ändern: Zimmer, Raumtypen, Heizzonen.
 *
 * Gates, alle `require_admin` — und alle nachgesehen, nicht vermutet:
 * `POST /rooms` (`api/v1/rooms.py:80`), `PATCH /rooms/{id}` (`:172`),
 * `DELETE /rooms/{id}` (`:383`); `POST`/`PATCH`/`DELETE /room-types`
 * (`api/v1/room_types.py:56`, `:114`, `:145`); `POST`/`PATCH`/`DELETE`
 * der Heizzonen (`api/v1/heating_zones.py:157`, `:200`, `:247`).
 *
 * Sprint 22 hat den Geltungsbereich erweitert: bis dahin stand hier nur
 * `PATCH`/`DELETE /rooms`, obwohl dieselbe Rolle auch Raumtypen und
 * Heizzonen entscheidet. Die Oberfläche hat das an drei Stellen nicht
 * gewusst (Befund des Hoteliers, 14.10.2026).
 */
export function darfStammdatenAendern(user: User | null): boolean {
  return user?.role === "admin";
}

/**
 * Hotelweite Schalter und Konfiguration ändern.
 *
 * Gates, alle `require_admin`: `POST /scenarios/{code}/activate` und
 * `/deactivate` (`api/v1/scenarios.py:181`, `:213`),
 * `PATCH /global-config` (`api/v1/global_config.py:65`),
 * `PATCH /rule-configs/global` (`api/v1/rule_configs.py:79`).
 *
 * **Warum eigenes Prädikat und nicht `darfStammdatenAendern`:** die Rolle
 * ist dieselbe, die Frage nicht. Ein Sommermodus fährt das **ganze Haus**
 * auf Frostschutz; ein Raumtyp ist ein Datensatz. Würde das Haus je eine
 * Rolle einführen, die Stammdaten pflegen darf, aber keine hotelweiten
 * Schalter, hängt der Unterschied schon an der richtigen Stelle.
 */
export function darfKonfigurationAendern(user: User | null): boolean {
  return user?.role === "admin";
}

/**
 * Benutzer anlegen, ändern, zurücksetzen, löschen — **und sie sehen**.
 *
 * Gate: `require_admin` an allen Mutationen in `api/v1/users.py` (`:87`,
 * `:132`, `:199`, `:228`) **und am Lesen** (`GET /users`). Das Lesen ist
 * die Ausnahme von der Regel „GET darf jeder Angemeldete" und steht so
 * in §5.30 begründet: die Liste trägt fremde E-Mail-Adressen, Rollen und
 * Aktiv-Kennzeichen.
 *
 * Deshalb ist „Benutzer" der einzige Eintrag, den die Seitenleiste
 * ausblendet (Sprint 22 T6) — dort gibt es für einen Mitarbeiter nichts
 * zu lesen.
 */
export function darfBenutzerVerwalten(user: User | null): boolean {
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

/**
 * Relais provisionieren, in Betrieb nehmen, Schutz-Sperre aufheben,
 * Fühler-Rolle umschalten (Sprint 24b, Paket 6).
 *
 * Gate: `require_admin` an allen fünf Mutationen in
 * `api/v1/relays.py` — `provision`, `commission` (POST und DELETE),
 * `release-protection` und `PATCH /devices/{id}/measure-only`.
 *
 * **Warum das hier eine eigene Funktion ist und nicht
 * `darfGeraeteVerwalten` mitbenutzt.** Die Gates sind heute dieselben,
 * die Entscheidungen nicht: ein Gerät einer Zone zuzuordnen ist
 * Stammdatenpflege, ein Panel scharf zu schalten ist ein Eingriff in ein
 * Gerät, das Netzspannung schaltet. Wer eines der beiden Rechte später
 * anders schneidet, soll dafür nicht die andere Oberfläche mitbewegen.
 */
export function darfRelaisSchalten(user: User | null): boolean {
  return user?.role === "admin";
}
