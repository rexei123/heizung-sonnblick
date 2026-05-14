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

test.describe("Sprint 9.16 Szenarien-UI", () => {
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
