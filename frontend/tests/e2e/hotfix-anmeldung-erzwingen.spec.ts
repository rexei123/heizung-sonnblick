import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Hotfix 16.10.2026: keine geschützte Seite ohne Sitzung.
 *
 * **Der Befund.** Ohne Anmeldung zeigte `/` das Dashboard-Gerüst mit
 * „Wert nicht verfügbar" auf allen Kacheln, ohne Konto in der Seitenleiste
 * und **ohne Weg zur Anmeldung**. Kein `middleware.ts`, und der
 * `AuthProvider` setzte bei 401 nur `user = null`, ohne umzuleiten.
 *
 * Fünf Prüfungen, und die fünfte ist die unscheinbarste:
 *
 * 1. abgemeldet `/` → landet auf `/login`
 * 2. abgemeldet `/zimmer` → `/login?next=%2Fzimmer`, nach der Anmeldung
 *    zurück auf `/zimmer`
 * 3. Sitzung läuft **während** der Nutzung ab (401 auf eine Abfrage) →
 *    `/login`
 * 4. `/login` selbst leitet nicht um (keine Schleife)
 * 5. `?next=` mit fremdem Ziel wird **nicht** gefolgt — sonst wäre die
 *    Anmeldung eine offene Weiterleitung, und zwar genau dort, wo der
 *    Nutzer sein Passwort gerade getippt hat
 *
 * Die Hülle aus `fixtures.ts` meldet standardmäßig einen Admin an; alle
 * Tests hier setzen ihren Zustand deshalb **ausdrücklich** nach dem
 * Catch-all (Playwright trifft die zuletzt registrierte Route zuerst).
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-16T06:00:00Z",
  last_login_at: "2026-10-16T06:00:00Z",
};

/** Abgemeldet: `/me` antwortet 401, wie der Server ohne Cookie. */
async function abgemeldet(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Nicht angemeldet" }),
    }),
  );
}

test.describe("Hotfix — Anmeldung erzwingen", () => {
  test("abgemeldet_dashboard_landet_auf_login", async ({ page }) => {
    await abgemeldet(page);
    await page.goto("/");

    await expect(page).toHaveURL(/\/login$/);
    // Und zwar das Formular, nicht das Gerüst: der Befund war, dass das
    // Dashboard mit leeren Kacheln stehenblieb.
    await expect(page.getByRole("button", { name: /Anmelden/i })).toBeVisible();
    await expect(page.getByText("Wert nicht verfügbar")).toHaveCount(0);
  });

  test("abgemeldet_unterseite_merkt_den_rueckweg", async ({ page }) => {
    await abgemeldet(page);
    await page.goto("/zimmer");

    await expect(page).toHaveURL(/\/login\?next=%2Fzimmer$/);

    // Jetzt anmelden: `/me` liefert ab hier den Admin, `/login` ein
    // Erfolgs-Paket. Danach muss die ursprüngliche Seite kommen.
    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(ADMIN),
      }),
    );
    await page.route(/.*\/api\/v1\/auth\/login(\?.*)?$/, (r: Route) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ user: ADMIN }),
      }),
    );

    // Ueber die Feld-IDs: `getByLabel(/Passwort/i)` trifft auch den
    // „Passwort anzeigen"-Knopf daneben (strict-mode-Verstoss).
    await page.locator("#email").fill("chef@hotel.example.com");
    await page.locator("#password").fill("egal-der-server-ist-gemockt");
    await page.getByRole("button", { name: /Anmelden/i }).click();

    await expect(page).toHaveURL(/\/zimmer$/);
  });

  test("sitzung_laeuft_waehrend_der_nutzung_ab", async ({ page }) => {
    // Angemeldet starten, dann antwortet der Server auf die Daten-Abfragen
    // mit 401 — der Fall „Sitzung ist abgelaufen, Seite steht noch offen".
    await page.route("**/api/v1/**", (r: Route) =>
      r.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Nicht angemeldet" }),
      }),
    );
    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(ADMIN),
      }),
    );

    await page.goto("/zimmer");

    // Die erste Abfrage mit 401 löst die harte Navigation aus.
    await expect(page).toHaveURL(/\/login\?next=/, { timeout: 15000 });
  });

  test("login_selbst_leitet_nicht_um", async ({ page }) => {
    await abgemeldet(page);
    await page.goto("/login");

    await expect(page.getByRole("button", { name: /Anmelden/i })).toBeVisible();
    // Keine Schleife: die Adresse bleibt, und es kommt kein `next` dazu.
    await expect(page).toHaveURL(/\/login$/);
  });

  test("fremdes_next_ziel_wird_nicht_gefolgt", async ({ page }) => {
    await abgemeldet(page);
    await page.goto("/login?next=https%3A%2F%2Ffremde.example%2Fphish");

    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(ADMIN),
      }),
    );
    await page.route(/.*\/api\/v1\/auth\/login(\?.*)?$/, (r: Route) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ user: ADMIN }),
      }),
    );

    // Ueber die Feld-IDs: `getByLabel(/Passwort/i)` trifft auch den
    // „Passwort anzeigen"-Knopf daneben (strict-mode-Verstoss).
    await page.locator("#email").fill("chef@hotel.example.com");
    await page.locator("#password").fill("egal-der-server-ist-gemockt");
    await page.getByRole("button", { name: /Anmelden/i }).click();

    // Das Dashboard, nicht die fremde Seite — und zwar als **exakte**
    // Adresse auf der eigenen Herkunft.
    //
    // Hier stand zuerst `toHaveURL(/\/$/)`, und der Test war auch **ohne**
    // die Pruefung gruen: ohne sie fuehrt `router.replace` wirklich nach
    // draussen, der Browser landet auf `chrome-error://chromewebdata/` —
    // und das endet ebenfalls auf einem Schraegstrich. Gemessen am
    // 16.10.2026 in der Mutationsprobe, die deshalb 0 rot meldete. Ein
    // Muster, das die Fehlerseite des Browsers mit dem Dashboard
    // verwechselt, prueft nichts (§5.55-Familie).
    //
    // `toHaveURL("/")` loest gegen die `baseURL` auf und vergleicht die
    // ganze Adresse — `chrome-error://…` faellt damit durch.
    await expect(page).toHaveURL("/");
    await expect(page).not.toHaveURL(/fremde\.example/);
  });
});
