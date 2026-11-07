import { STANDARD_ADMIN, test, expect, type Page } from "./fixtures";

/**
 * Sprint 9.13b — Sidebar-Migration auf 5 Gruppen + Mobile-Sheet via
 * shadcn. Stub-Pages mit EmptyState-Komponente.
 *
 * **Die Zahl der Eintraege steht nicht mehr hier, sondern nur in den
 * Pruefungen** (Stand 07.11.2026: 12 fuer Admin, 11 fuer Mitarbeiter).
 * Sie hat sich dreimal geaendert — 14, dann 15, jetzt 12 — und eine
 * Zahl in der Dateiueberschrift wird beim Nachziehen regelmaessig
 * vergessen. Jede Pruefung nennt ihre Zahl mit Grund an der Stelle, an
 * der sie zaehlt (CLAUDE.md Paragraph 5.77).
 *
 * Backend-Mock: nur fuer / (Dashboard-Empty-State). Sidebar-Tests sind
 * Layout-getrieben, brauchen keinen API-State.
 */

test.describe("Sprint 9.13b Sidebar-Migration", () => {
  /**
   * Sprint 22 T6: die Seitenleiste hängt seit diesem Sprint an der Rolle
   * — „Benutzer" sieht nur ein Administrator. Deshalb fahren beide
   * Prüfungen ihre Rolle **ausdrücklich** (Bedingung des Hoteliers,
   * 14.10.2026), und zwar **nach** dem `**\/api\/v1\/**`-Fang:
   * Playwright trifft die zuletzt registrierte Route zuerst, der Fang
   * würde `/auth/me` sonst mit `[]` beantworten und `user` bliebe `null`.
   *
   * Genau daran ist diese Datei zuerst gefallen: der Fang verdeckte die
   * Admin-Hülle aus `fixtures.ts`, und ein `null`-Nutzer zählt 13 statt
   * 14 Einträge. Der Standard der Hülle ersetzt also keine
   * Rollen-Angabe, er ist nur der Normalfall für Tests, die von der
   * Rolle nichts wissen wollen.
   */
  async function mitRolle(page: Page, rolle: "admin" | "mitarbeiter") {
    // Mock /devices weil layout via main wrappt — Page rendert auch ohne
    // Backend, aber TanStack-Query wuerde sonst Netzwerk versuchen.
    await page.route("**/api/v1/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...STANDARD_ADMIN, role: rolle }),
      }),
    );
  }

  /**
   * Paket 1 (25.10.2026): die Zahlen sind von 14/13 auf 15/14 gestiegen —
   * der Eintrag „Handbuch" ist dazugekommen, lesbar fuer **alle** Rollen.
   *
   * **Am 26.10. korrigiert:** er stand zuerst in einer eigenen Gruppe
   * „Hilfe" am Ende (also 6 Gruppen) und sitzt seither in „Uebersicht",
   * direkt unter „Belegungen" — Entscheidung des Betreibers. Damit sind
   * es wieder **5** Gruppen. Beide Aenderungen stehen
   * hier mit Grund, damit niemand sie spaeter fuer stillschweigend
   * nachgezogene Zahlen haelt.
   */
  test("Desktop-Sidebar zeigt Admin 12 Eintraege in 5 Gruppen", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mitRolle(page, "admin");

    await page.goto("/");

    const nav = page.getByRole("navigation", { name: "Hauptnavigation" });
    await expect(nav).toBeVisible();

    // 5 Gruppen-Header
    const groups = ["Übersicht", "Steuerung", "Geräte", "Analyse", "Einstellungen"];
    for (const group of groups) {
      await expect(nav.getByRole("heading", { level: 3, name: group })).toBeVisible();
    }

    await expect(nav.getByRole("link", { name: "Benutzer" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Handbuch" })).toBeVisible();
    // Es gibt keine Gruppe „Hilfe" mehr — eine Ueberschrift fuer einen
    // einzigen Eintrag war Rahmen ohne Inhalt.
    await expect(nav.getByRole("heading", { level: 3, name: "Hilfe" })).toHaveCount(0);

    // **12, nicht 15** — am 07.11.2026 sind „Profile", „Saison" und
    // „Gateway" aus der Leiste genommen worden (Sprint 25 T8). Alle drei
    // Seiten zeigten nur „In Vorbereitung". Die Routen bleiben
    // erreichbar, sie stehen nur nicht mehr im Menue; der Stub-Test
    // weiter unten prueft genau das.
    const links = nav.getByRole("link");
    await expect(links).toHaveCount(12);
  });

  test("Desktop-Sidebar zeigt Mitarbeiter 11 Eintraege ohne Benutzer", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mitRolle(page, "mitarbeiter");

    await page.goto("/");

    const nav = page.getByRole("navigation", { name: "Hauptnavigation" });
    await expect(nav).toBeVisible();

    // Die Gruppe „Einstellungen" bleibt — sie verliert nur einen von
    // drei Einträgen (es waren sechs, bis „Profile", „Saison" und
    // „Gateway" am 07.11.2026 aus der Leiste gingen). Eine Gruppe fällt
    // erst weg, wenn sie leer würde.
    await expect(
      nav.getByRole("heading", { level: 3, name: "Einstellungen" }),
    ).toBeVisible();

    await expect(nav.getByRole("link", { name: "Benutzer" })).toHaveCount(0);
    // Das Handbuch ist fuer alle Rollen lesbar — es ist der einzige
    // Eintrag, bei dem das ausdruecklich gefordert war.
    await expect(nav.getByRole("link", { name: "Handbuch" })).toBeVisible();
    // 11 = die 12 des Admin minus „Benutzer" (Sprint 25 T8, siehe oben).
    await expect(nav.getByRole("link")).toHaveCount(11);
  });

  test("Mobile-Sheet oeffnet sich via Hamburger und schliesst nach Navigation", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.route("**/api/v1/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    await page.goto("/");

    const hamburger = page.getByRole("button", { name: "Navigation öffnen" });
    await expect(hamburger).toBeVisible();

    await hamburger.click();

    // Sheet ist offen — NavList sichtbar mit Dashboard-Link
    const dashboardLink = page.getByRole("link", { name: /Dashboard/i });
    await expect(dashboardLink).toBeVisible();

    // A11y-Labels (sr-only, Radix DialogTitle/Description Requirement)
    await expect(page.getByRole("dialog", { name: "Navigation" })).toBeVisible();
    await expect(page.getByText("Hauptnavigation der Heizungssteuerung")).toBeAttached();

    // Klick schliesst Sheet automatisch (onNavigate)
    await page.getByRole("link", { name: /Zimmerübersicht/i }).click();
    await expect(page).toHaveURL(/\/zimmer$/);
    // Nach Navigation: Sheet weg, Hamburger wieder erreichbar
    await expect(hamburger).toBeVisible();
  });

  test("Stub-Pages laden mit EmptyState-Komponente", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });

    // Sprint 9.17 (T10): Sprint-Nummer-Badges sind raus, Stubs zeigen
    // einheitlich „In Vorbereitung".
    // Sprint 25 T8 (07.11.2026): diese beiden Seiten stehen nicht mehr in
    // der Seitenleiste — aber ihre Routen bleiben erreichbar und leiten
    // NICHT um. Genau das prueft dieser Test weiterhin: wer einen alten
    // Lesezeichen-Link oeffnet, landet auf einer Seite, die sagt, was sie
    // ist. Eine Umleitung aufs Dashboard waere eine stumme Luege.
    const stubs: { path: string; title: string }[] = [
      { path: "/profile", title: "Profile" },
      { path: "/einstellungen/saison", title: "Saison" },
    ];

    for (const stub of stubs) {
      await page.goto(stub.path);
      await expect(page.getByRole("heading", { level: 1, name: stub.title })).toBeVisible();
      await expect(page.getByText("In Vorbereitung")).toBeVisible();
    }
  });

  test("Pre-Login-Routen (/login, /auth/*) zeigen KEINE Sidebar", async ({ page }) => {
    // B-9.17b-2: AppShell-Sidebar war kurz auf /login sichtbar nach Logout-Redirect.
    // AppShell blendet jetzt fuer /login + /auth/* die Sidebar aus.
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.route("**/api/v1/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    for (const path of ["/login", "/auth/change-password"]) {
      await page.goto(path);
      // Sidebar darf weder als Desktop-Nav noch als Mobile-Hamburger sichtbar sein
      await expect(page.getByRole("navigation", { name: "Hauptnavigation" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Navigation öffnen" })).toHaveCount(0);
    }
  });

  test("Active-Route-Highlight greift auch bei Untermenue", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.route("**/api/v1/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    // Geprueft wird an „API & Webhooks", seit der Saison-Eintrag am
    // 07.11.2026 aus der Leiste genommen wurde (Sprint 25 T8). Die Frage
    // ist dieselbe und sie ist der Grund fuer diesen Test: ein
    // startsWith("/einstellungen") wuerde jeden Untermenue-Eintrag
    // gleichzeitig markieren.
    await page.goto("/einstellungen/api");

    // Der aufgerufene Eintrag hat aria-current=page
    const apiLink = page
      .getByRole("navigation", { name: "Hauptnavigation" })
      .getByRole("link", { name: /API & Webhooks/i });
    await expect(apiLink).toHaveAttribute("aria-current", "page");

    // Hotel-Link in derselben Gruppe ist NICHT aktiv (sonst hätte
    // startsWith /einstellungen alle Untermenues markiert)
    const hotelLink = page
      .getByRole("navigation", { name: "Hauptnavigation" })
      .getByRole("link", { name: /^Hotel$/ });
    await expect(hotelLink).not.toHaveAttribute("aria-current", "page");
  });
});
