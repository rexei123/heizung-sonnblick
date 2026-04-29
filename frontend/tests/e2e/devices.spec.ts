import { test, expect } from "@playwright/test";

/**
 * Sprint 7 Smoke-Tests fuer das Frontend-Dashboard.
 *
 * Backend wird gemockt via Route-Interception, damit Tests auch ohne
 * laufenden FastAPI-Container gruen sind (CI-tauglich).
 */

const SAMPLE_DEVICE = {
  id: 42,
  dev_eui: "0011223344556677",
  app_eui: null,
  kind: "thermostat",
  vendor: "mclimate",
  model: "Vicki",
  label: "Vicki Test 101",
  heating_zone_id: null,
  is_active: true,
  last_seen_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
};

const SAMPLE_READINGS = [
  {
    time: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
    fcnt: 3,
    temperature: 22.4,
    setpoint: 21.0,
    valve_position: 80,
    battery_percent: 75,
    rssi_dbm: -82,
    snr_db: 8.0,
  },
  {
    time: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    fcnt: 2,
    temperature: 22.0,
    setpoint: 21.0,
    valve_position: 70,
    battery_percent: 75,
    rssi_dbm: -85,
    snr_db: 7.5,
  },
];

test.describe("Frontend-Dashboard (Sprint 7)", () => {
  test("Geraeteliste laedt und zeigt eine Zeile pro Geraet", async ({ page }) => {
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([SAMPLE_DEVICE]),
      }),
    );

    await page.goto("/devices");

    await expect(page.getByRole("heading", { name: "Geräte" })).toBeVisible();
    await expect(page.getByText("Vicki Test 101")).toBeVisible();
    await expect(page.getByText("0011223344556677")).toBeVisible();
    await expect(page.getByText("aktiv")).toBeVisible();
  });

  test("Empty-State erscheint bei leerer Liste", async ({ page }) => {
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      }),
    );

    await page.goto("/devices");
    await expect(page.getByText("Noch keine Geräte")).toBeVisible();
  });

  test("Detail-View zeigt KPI-Cards und Chart-Container", async ({ page }) => {
    await page.route(`**/api/v1/devices/${SAMPLE_DEVICE.id}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_DEVICE),
      }),
    );
    await page.route(
      `**/api/v1/devices/${SAMPLE_DEVICE.id}/sensor-readings*`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(SAMPLE_READINGS),
        }),
    );

    await page.goto(`/devices/${SAMPLE_DEVICE.id}`);

    await expect(page.getByRole("heading", { name: "Vicki Test 101" })).toBeVisible();
    // Mehrfach-Vorkommen (KPI + Chart-Legend + Tabellen-Reihe) — first() reicht.
    await expect(page.getByText("Temperatur").first()).toBeVisible();
    await expect(page.getByText("22.4 °C").first()).toBeVisible();
    await expect(page.locator('[data-testid="sensor-readings-chart"]')).toBeVisible();
  });

  test("Detail-View 404 bei unbekannter Device-ID", async ({ page }) => {
    await page.route("**/api/v1/devices/9999", (route) =>
      route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Device 9999 nicht gefunden" }),
      }),
    );

    await page.goto("/devices/9999");
    await expect(page.getByText("Gerät nicht gefunden")).toBeVisible();
  });
});
