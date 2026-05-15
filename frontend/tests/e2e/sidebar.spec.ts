import { test, expect } from "@playwright/test";

/**
 * Sprint 9.13b — Sidebar-Migration auf 14 Eintraege in 5 Gruppen +
 * Mobile-Sheet via shadcn. Stub-Pages (8) mit EmptyState-Komponente.
 *
 * Backend-Mock: nur fuer / (Dashboard-Empty-State). Sidebar-Tests sind
 * Layout-getrieben, brauchen keinen API-State.
 */

test.describe("Sprint 9.13b Sidebar-Migration", () => {
  test("Desktop-Sidebar zeigt 14 Eintraege in 5 Gruppen", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    // Mock /devices weil layout via main wrappt — Page rendert auch ohne
    // Backend, aber TanStack-Query wuerde sonst Netzwerk versuchen.
    await page.route("**/api/v1/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    await page.goto("/");

    const nav = page.getByRole("navigation", { name: "Hauptnavigation" });
    await expect(nav).toBeVisible();

    // 5 Gruppen-Header
    const groups = ["Übersicht", "Steuerung", "Geräte", "Analyse", "Einstellungen"];
    for (const group of groups) {
      await expect(nav.getByRole("heading", { level: 3, name: group })).toBeVisible();
    }

    // 14 Nav-Links
    const links = nav.getByRole("link");
    await expect(links).toHaveCount(14);
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

    await page.goto("/einstellungen/saison");

    // Saison-Link hat aria-current=page
    const saisonLink = page
      .getByRole("navigation", { name: "Hauptnavigation" })
      .getByRole("link", { name: /Saison/i });
    await expect(saisonLink).toHaveAttribute("aria-current", "page");

    // Hotel-Link in derselben Gruppe ist NICHT aktiv (sonst hätte
    // startsWith /einstellungen alle Untermenues markiert)
    const hotelLink = page
      .getByRole("navigation", { name: "Hauptnavigation" })
      .getByRole("link", { name: /^Hotel$/ });
    await expect(hotelLink).not.toHaveAttribute("aria-current", "page");
  });
});
