import { expect, test } from "@playwright/test";

/**
 * Sprint 9.16 T10 — Warn-Banner auf /einstellungen/temperaturen-zeiten,
 * wenn ``summer_mode`` global aktiv ist.
 */

const RULE_CONFIG = {
  id: 1,
  t_occupied: "21.0",
  t_vacant: "18.0",
  t_night: "19.0",
  night_start: "00:00:00",
  night_end: "06:00:00",
  preheat_minutes_before_checkin: 90,
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

const SUMMER_SCENARIO_BASE = {
  id: 1,
  code: "summer_mode",
  name: "Sommermodus",
  description: "Heizthermostate funktionslos.",
  is_system: true,
  default_active: false,
  parameter_schema: null,
  default_parameters: null,
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

test.describe("Sprint 9.16 Warn-Banner Temperaturen+Zeiten", () => {
  test("Banner sichtbar bei aktivem Sommermodus", async ({ page }) => {
    await page.route("**/api/v1/rule-configs/global", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(RULE_CONFIG),
      }),
    );
    await page.route("**/api/v1/scenarios", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { ...SUMMER_SCENARIO_BASE, current_global_assignment_active: true },
        ]),
      }),
    );

    await page.goto("/einstellungen/temperaturen-zeiten");

    const banner = page.getByRole("alert").filter({ hasText: "Sommermodus aktiv" });
    await expect(banner).toBeVisible();
    await expect(banner.getByRole("link", { name: /Verwalten/ })).toHaveAttribute(
      "href",
      "/szenarien",
    );
  });

  test("Kein Banner bei inaktivem Sommermodus", async ({ page }) => {
    await page.route("**/api/v1/rule-configs/global", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(RULE_CONFIG),
      }),
    );
    await page.route("**/api/v1/scenarios", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { ...SUMMER_SCENARIO_BASE, current_global_assignment_active: false },
        ]),
      }),
    );

    await page.goto("/einstellungen/temperaturen-zeiten");

    // Inhalt der Page muss da sein
    await expect(
      page.getByRole("heading", { level: 1, name: "Temperaturen & Zeiten" }),
    ).toBeVisible();
    // Kein Sommermodus-Banner
    await expect(page.getByText("Sommermodus aktiv.")).toHaveCount(0);
  });
});
