/**
 * Gemeinsame Test-Hülle: jeder Test ist standardmäßig als **Administrator**
 * angemeldet (Sprint 22 T8).
 *
 * **Der Anlass sind vier Fälle derselben Art.** Seit die Oberfläche Knöpfe
 * nach Rolle zeigt, fällt ein Test um, der `/auth/me` nicht mockt: `user`
 * bleibt `null`, `null` darf nichts, und der Knopf, den der Test klicken
 * will, ist weg. Das traf `devices-pairing` (Sprint 21 A2), `szenarien`
 * (Sprint 22 T2), `temperaturen-zeiten` samt Warn-Banner und die
 * 20c-Pairing-Auswahl (T4/T5).
 *
 * Diese Tests waren nicht **gegen** die Rolle geprüft, sondern **blind**
 * für sie. Eine Lesson hätte das beschrieben; diese Hülle macht es
 * unmöglich — der Normalfall im Betrieb ist ein angemeldeter Nutzer, und
 * bei `AUTH_ENABLED=false` liefert `/me` sogar einen Admin (den
 * System-User). Der Standard bildet also die Wirklichkeit ab und nicht
 * eine Bequemlichkeit.
 *
 * **Die Bedingung, unter der das zulässig ist** (Hotelier, 14.10.2026):
 *
 * > Rollen-Tests setzen ihre Rolle weiterhin **ausdrücklich**, und zwar
 * > beide Rollen je Prüfung — nicht über den Standard.
 *
 * Das funktioniert, weil Playwright die **zuletzt registrierte** Route
 * zuerst trifft: eine eigene `/auth/me`-Route im Test gewinnt gegen die
 * hier. Ein Rollen-Test, der sich auf den Standard verließe, würde nur
 * „Admin sieht den Knopf" prüfen und nie die andere Richtung — deshalb
 * bleibt die ausdrückliche Rolle Pflicht und ist in
 * `sprint22-rollen-*.spec.ts` auch so gefahren.
 *
 * **Verwendung:** `import { test, expect } from "./fixtures";` statt aus
 * `@playwright/test`. Typen (`Page`, `Route`, …) kommen von hier mit.
 */

import { test as basis, expect as basisExpect } from "@playwright/test";

export { expect } from "@playwright/test";
export type {
  APIRequestContext,
  APIResponse,
  BrowserContext,
  ConsoleMessage,
  Locator,
  Page,
  Request,
  Response,
  Route,
} from "@playwright/test";

/**
 * Der Standard-Nutzer. Admin, weil das im Betrieb der Normalfall ist und
 * weil ein Test, der eine **engere** Rolle braucht, sie ohnehin selbst
 * setzen muss.
 */
export const STANDARD_ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-14T06:00:00Z",
  last_login_at: "2026-10-14T06:00:00Z",
};

export const test = basis.extend<{ ungemockteApiAnfragen: void; angemeldet: void }>({
  /**
   * Rückhalt: eine API-Anfrage, die kein Mock abdeckt, verlässt den
   * Browser nicht — und der Test fällt mit dem Pfad in der Meldung.
   *
   * **Der Anlass.** Ungemockte Anfragen gehen über den Rewrite aus
   * `next.config.mjs` an `API_PROXY_TARGET`, und das ist lokal
   * `https://heizung-test.hoteltec.at` — develop, also die Produktion
   * dieses Hauses (`tests/proxy-ziel.ts` trägt den Befund). Im Lauf vom
   * 25.10.2026 sind sie nur am TLS-Handshake gescheitert; das ist Zufall
   * und kein Schutz.
   *
   * **Warum zusätzlich zur Schranke in `playwright.config.ts`.** Die
   * Schranke dort prüft, womit Playwright den `webServer` startet. Lokal
   * gilt aber `reuseExistingServer: true`: läuft auf dem Port schon ein
   * Next (etwa ein `npm run dev` des Betreibers), startet Playwright
   * keinen eigenen, und die geprüfte Umgebung erreicht diesen Prozess
   * nie — er proxyt weiter nach seiner eigenen `.env.local`. Die
   * Konfig-Schranke gilt also nur auf der Ebene „Server, den dieser Lauf
   * selbst startet" (§5.83). Dieser Rückhalt greift eine Ebene tiefer, im
   * Browser, und ist von jedem Server unabhängig.
   *
   * **Warum `abort` und zusätzlich ein Fehlschlag.** Nur abzubrechen
   * würde den Test eine Fehleransicht zeigen lassen — er wäre je nach
   * Prüfung weiter grün, und der fehlende Mock bliebe unsichtbar
   * (§5.55-Familie: ein grüner Lauf, der nichts geprüft hat). Der
   * Fehlschlag am Ende nennt die Pfade, die niemand gemockt hat.
   *
   * **Das Muster ist an den Rewrite gebunden, nicht an das Wort „api".**
   * Zuerst stand hier das Glob `**\/api\/**`. Der erste Lauf hat damit
   * 77 Fehlschläge gemeldet, die keine API-Anfrage waren, sondern ein
   * Next-Bündel: `/_next/static/chunks/app/einstellungen/api/page-*.js`
   * — das `api` steckt im Seitenpfad, das Glob trifft es mitten im Weg.
   * Abgebrochen hat das die Seite selbst zerlegt (zehn Folge-Timeouts).
   * Geprüft wird deshalb der **Pfad-Anfang**, weil nur das den Rechner
   * über den Rewrite verlassen kann. Wer in `next.config.mjs` einen
   * zweiten Rewrite anlegt, erweitert diese Bedingung mit — sonst hat
   * die Schranke einen Weg, den sie nicht sieht (§5.79).
   *
   * **`route.fallback()`, nie `route.continue()`.** Ein Mock-Zweig für
   * eine unerwartete Methode („alles außer GET") stand in fünf Dateien
   * auf `continue()` — und das heißt „an den echten Server schicken",
   * also am Rückhalt vorbei in den Rewrite. `fallback()` gibt an die
   * nächste passende Route weiter und landet damit hier. Die Zweige
   * feuern heute nicht; der Unterschied zählt an dem Tag, an dem einer
   * feuert, und dann ist er nicht zu sehen (§5.78-Familie).
   *
   * **Die Reihenfolge trägt das.** Playwright trifft die **zuletzt**
   * registrierte Route zuerst. Weil diese hier als erstes registriert
   * wird — Fixtures laufen vor `beforeEach` und vor dem Test-Rumpf —, ist
   * sie der letzte Ausweg und nie der erste Treffer. Ein Mock im Test
   * gewinnt immer.
   */
  ungemockteApiAnfragen: [
    async ({ page }, use) => {
      const ungemockt: string[] = [];

      await page.route(
        (url) => url.pathname.startsWith("/api/"),
        async (route) => {
          const anfrage = route.request();
          ungemockt.push(`${anfrage.method()} ${new URL(anfrage.url()).pathname}`);
          await route.abort("blockedbyclient");
        },
      );

      await use();

      basisExpect(
        [...new Set(ungemockt)].sort(),
        "Ungemockte API-Anfragen — sie wären über den Next-Rewrite an " +
          "API_PROXY_TARGET gegangen (tests/proxy-ziel.ts). Jede dieser " +
          "Routen braucht ein page.route() im Test.",
      ).toEqual([]);
    },
    { auto: true },
  ],

  angemeldet: [
    async ({ page, ungemockteApiAnfragen }, use) => {
      // Die Abhängigkeit ist die Reihenfolge: der Rückhalt muss **vor**
      // dieser Route registriert sein, damit er der letzte Ausweg bleibt
      // und nicht die `/auth/me`-Antwort abfängt. Deklarationsreihenfolge
      // in `extend` wäre eine Annahme über Playwright-Interna, die
      // Abhängigkeit ist eine Zusicherung (§5.83).
      void ungemockteApiAnfragen;

      await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(STANDARD_ADMIN),
        }),
      );
      await use();
    },
    { auto: true },
  ],
});
