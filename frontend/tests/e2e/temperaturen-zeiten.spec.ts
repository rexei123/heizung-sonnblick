import { expect, test } from "@playwright/test";

/**
 * Sprint 9.14 T6 — Frontend-Tests fuer /einstellungen/temperaturen-zeiten.
 *
 * Backend gemockt via page.route. Kein laufender FastAPI noetig.
 */

const INITIAL = {
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

test.describe("Sprint 9.14 Globale Temperaturen + Zeiten", () => {
  test("Page lädt mit beiden Tabs und Inline-Edit funktioniert", async ({ page }) => {
    let current = { ...INITIAL };

    await page.route("**/api/v1/rule-configs/global", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(current),
        });
        return;
      }
      if (route.request().method() === "PATCH") {
        const payload = route.request().postDataJSON();
        current = { ...current, ...payload, updated_at: new Date().toISOString() };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(current),
        });
        return;
      }
      await route.continue();
    });

    await page.goto("/einstellungen/temperaturen-zeiten");

    // Beide Tabs sichtbar
    await expect(page.getByRole("tab", { name: "Globale Zeiten" })).toBeVisible();
    await expect(
      page.getByRole("tab", { name: "Globale Temperaturen" }),
    ).toBeVisible();

    // Wechseln in Temperaturen-Tab
    await page.getByRole("tab", { name: "Globale Temperaturen" }).click();

    // Klick auf "Zimmer belegt"-Wert oeffnet Edit
    await page
      .getByRole("button", { name: "Zimmer belegt bearbeiten" })
      .click();
    const occupiedInput = page.getByRole("textbox", { name: "Zimmer belegt" });
    await expect(occupiedInput).toBeVisible();

    // Out-of-Range: 30 ist ueber dem Max 26
    await occupiedInput.fill("30");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alert").first()).toContainText("Bereich");
    // Wert ist noch alt im UI (Edit-Mode haengt fest)
    await expect(occupiedInput).toBeVisible();

    // Valid: 22 ist in Range
    await occupiedInput.fill("22");
    await page.keyboard.press("Enter");

    // Toast erscheint
    await expect(
      page.getByText("Gespeichert — Engine übernimmt in ≤ 60 s"),
    ).toBeVisible();

    // Nach Save: Display zeigt neuen Wert mit Einheit
    await expect(
      page.getByRole("button", { name: "Zimmer belegt bearbeiten" }),
    ).toContainText("22 °C");

    // Reload-Persistenz: Page erneut laden, Wert kommt vom Mock-State
    await page.reload();
    await page.getByRole("tab", { name: "Globale Temperaturen" }).click();
    await expect(
      page.getByRole("button", { name: "Zimmer belegt bearbeiten" }),
    ).toContainText("22 °C");
  });
});
