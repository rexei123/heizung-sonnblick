import { expect, test } from "@playwright/test";

/**
 * Sprint 9.16 T10 — Frontend-Tests fuer /szenarien.
 *
 * Backend gemockt via page.route. Status-Wechsel beim PATCH-aequivalenten
 * POST wird im Mock-State getrackt, damit der Reload-Pfad konsistent ist.
 */

const BASE_SCENARIO = {
  id: 1,
  code: "summer_mode",
  name: "Sommermodus",
  description:
    "Heizthermostate funktionslos — Klimaanlage übernimmt. Alle Räume auf Frostschutz.",
  is_system: true,
  default_active: false,
  parameter_schema: null,
  default_parameters: null,
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

/**
 * Sprint 22 T2: der Sommermodus-Schalter erscheint nur fuer `admin`
 * (`POST /scenarios/{code}/activate` ist `require_admin`,
 * `api/v1/scenarios.py:181`). Ohne `/auth/me`-Mock bleibt `user` in den
 * Tests `null`, und `null` darf nichts — der Schalter waere dann weg und
 * dieser Test koennte ihn nicht klicken.
 *
 * Im Betrieb liefert `/me` auch bei `AUTH_ENABLED=false` einen Admin
 * (den System-User); der Mock stellt also den Normalfall her.
 */
const MOCK_ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-14T06:00:00Z",
  last_login_at: "2026-10-14T06:00:00Z",
};

test.describe("Sprint 9.16 Szenarien-UI", () => {
  test.beforeEach(async ({ page }) => {
    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_ADMIN),
      }),
    );
  });

  test("Card laedt, AlertDialog steuert Aktivieren+Toast", async ({ page }) => {
    let isActive = false;

    await page.route("**/api/v1/scenarios", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { ...BASE_SCENARIO, current_global_assignment_active: isActive },
        ]),
      });
    });
    await page.route(
      "**/api/v1/scenarios/summer_mode/activate",
      async (route) => {
        isActive = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...BASE_SCENARIO,
            current_global_assignment_active: true,
          }),
        });
      },
    );
    await page.route(
      "**/api/v1/scenarios/summer_mode/deactivate",
      async (route) => {
        isActive = false;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...BASE_SCENARIO,
            current_global_assignment_active: false,
          }),
        });
      },
    );

    await page.goto("/szenarien");

    // Heading + Card
    await expect(page.getByRole("heading", { level: 1, name: "Szenarien" })).toBeVisible();
    await expect(page.getByText("Sommermodus")).toBeVisible();

    // Status-Badge: Inaktiv
    await expect(page.getByText("Inaktiv").first()).toBeVisible();

    // Switch klick → AlertDialog
    const toggle = page.getByRole("switch", { name: "Sommermodus aktivieren" });
    await toggle.click();
    await expect(
      page.getByRole("alertdialog").getByText("Sommermodus aktivieren?"),
    ).toBeVisible();

    // Cancel: kein State-Change
    await page.getByRole("button", { name: "Abbrechen" }).click();
    await expect(page.getByRole("alertdialog")).not.toBeVisible();
    await expect(page.getByText("Inaktiv").first()).toBeVisible();

    // Erneut aktivieren + bestaetigen
    await toggle.click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Sommermodus aktivieren" })
      .click();

    // Toast + Status-Badge Aktiv
    await expect(page.getByText(/Sommermodus aktiviert/)).toBeVisible();
    await expect(page.getByText("Aktiv").first()).toBeVisible();
  });
});
