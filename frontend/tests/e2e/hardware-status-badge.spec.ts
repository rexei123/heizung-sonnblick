import { test, expect } from "@playwright/test";

/**
 * Sprint 9.13c TC6 — Frontend-Tests fuer HardwareStatusBadge an drei
 * Integrationsstellen: /devices-Liste, /devices/[id]-Detail-Page,
 * /zimmer/[id]-Geraete-Tab.
 *
 * Backend wird via page.route gemockt — kein laufender FastAPI noetig.
 */

const SAMPLE_DEVICE = {
  id: 42,
  dev_eui: "0011223344556677",
  app_eui: null,
  kind: "thermostat",
  vendor: "mclimate",
  model: "Vicki",
  label: "Vicki Test 101",
  heating_zone_id: 7,
  is_active: true,
  last_seen_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

const SAMPLE_HW_STATUS = {
  status: "active",
  last_seen: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  frames_in_window: 3,
  window_minutes: 30,
};

const SAMPLE_ROOM = {
  id: 1,
  number: "101",
  display_name: null,
  room_type_id: 1,
  floor: 1,
  orientation: "S",
  status: "vacant",
  notes: null,
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

const SAMPLE_HEATING_ZONE = {
  id: 7,
  room_id: 1,
  kind: "bedroom",
  name: "Schlafbereich",
  is_towel_warmer: false,
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

test.describe("Sprint 9.13c Hardware-Status-Badge", () => {
  test("Badge erscheint auf /devices-Liste in neuer Spalte", async ({ page }) => {
    // Playwright matcht LIFO — spezifische Routes zuletzt registrieren.
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([SAMPLE_DEVICE]),
      }),
    );
    await page.route(
      `**/api/v1/devices/${SAMPLE_DEVICE.id}/hardware-status`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SAMPLE_HW_STATUS),
        }),
    );

    await page.goto("/devices");

    // Sprint 9.13c Wording: Spalte heisst jetzt "Status" (Hardware-Status-Badge)
    await expect(page.locator("th").filter({ hasText: "Status" })).toBeVisible();
    // Detailed-Variante: Badge mit "Aktiv" plus "Zuletzt: ..."-Hinweis
    await expect(page.getByText("Aktiv").first()).toBeVisible();
    await expect(page.getByText(/Zuletzt:/)).toBeVisible();
  });

  test("Badge erscheint auf /devices/[id] Detail-Page", async ({ page }) => {
    await page.route(
      `**/api/v1/devices/${SAMPLE_DEVICE.id}/hardware-status`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SAMPLE_HW_STATUS),
        }),
    );
    await page.route(
      `**/api/v1/devices/${SAMPLE_DEVICE.id}/sensor-readings*`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        }),
    );
    await page.route(`**/api/v1/devices/${SAMPLE_DEVICE.id}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_DEVICE),
      }),
    );

    await page.goto(`/devices/${SAMPLE_DEVICE.id}`);

    // Sprint 9.13c Wording: Detail-Page-Label heisst jetzt "Status"
    await expect(page.getByText("Status", { exact: true })).toBeVisible();
    // Detailed-Variante: Aktiv-Label + Zuletzt-Hinweis
    await expect(page.getByText("Aktiv").first()).toBeVisible();
    await expect(page.getByText(/Zuletzt:/)).toBeVisible();
  });

  test("Badge erscheint auf /zimmer/[id] Geraete-Tab", async ({ page }) => {
    // Playwright matcht LIFO: catch-all ZUERST, dann spezifische — die
    // spezifischen werden dann zuerst geprueft.
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      }),
    );
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([SAMPLE_DEVICE]),
      }),
    );
    await page.route(
      `**/api/v1/devices/${SAMPLE_DEVICE.id}/hardware-status`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SAMPLE_HW_STATUS),
        }),
    );
    await page.route("**/api/v1/rooms/1/heating-zones", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([SAMPLE_HEATING_ZONE]),
      }),
    );
    await page.route("**/api/v1/rooms/1", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_ROOM),
      }),
    );

    await page.goto("/zimmer/1");

    // Geraete-Tab aktivieren
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    // Compact-Badge neben Bezeichnung sichtbar
    await expect(page.getByText("Aktiv").first()).toBeVisible();
  });
});
