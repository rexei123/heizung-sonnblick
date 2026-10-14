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

import { test as basis } from "@playwright/test";

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

export const test = basis.extend<{ angemeldet: void }>({
  angemeldet: [
    async ({ page }, use) => {
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
