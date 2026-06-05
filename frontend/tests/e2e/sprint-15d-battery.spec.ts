import { test, expect, type Page } from "@playwright/test";

/**
 * Sprint 15d (AE-65) — Batterie-Sichtbarkeit (PR2 Frontend).
 *
 * - BatteryBadge in der /devices-Tabelle: 3+1 Zustände aus device.battery_state.
 * - statusScore-Redesign: Sortierung über BEIDE Health-Achsen (max), die
 *   health_state-Achse schlägt die Batterie-Achse (offline > batt-kritisch).
 *
 * Backend gemockt via Route-Interception (kein FastAPI nötig), Muster wie
 * devices.spec.ts.
 */

const NOW = Date.now();
const iso = (offsetMs = 0) => new Date(NOW - offsetMs).toISOString();

type HealthState = "healthy" | "degraded" | "silent" | "suspicious";
type BatteryState = "ok" | "warn" | "kritisch" | "unbekannt";

function makeDevice(
  id: number,
  label: string,
  healthState: HealthState,
  batteryState: BatteryState,
  batteryPercent: number | null,
) {
  return {
    id,
    dev_eui: id.toString(16).padStart(16, "0"),
    app_eui: null,
    kind: "thermostat" as const,
    vendor: "mclimate" as const,
    model: "vicki",
    label,
    heating_zone_id: null,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: iso(5 * 60 * 1000),
    firmware_version: "4.2",
    health_state: healthState,
    battery_state: batteryState,
    created_at: iso(86400 * 1000),
    updated_at: iso(),
    hardware_number: null,
    heating_zone: null,
    active_override: null,
    latest_reading:
      batteryPercent === null
        ? null
        : {
            valve_position: 40,
            open_window: false,
            attached_backplate: true,
            temperature: 21.0,
            battery_percent: batteryPercent,
            recorded_at: iso(5 * 60 * 1000),
          },
  };
}

async function mockDevices(page: Page, devices: unknown[]) {
  await page.route("**/api/v1/devices*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(devices),
    }),
  );
  // HardwareStatusBadge fetcht je Gerät /hardware-status — generisch mocken.
  await page.route("**/api/v1/devices/*/hardware-status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "inactive",
        last_seen: null,
        frames_in_window: 0,
        window_minutes: 30,
      }),
    }),
  );
}

test.describe("Sprint 15d — Batterie-Badge + statusScore", () => {
  test("BatteryBadge zeigt 3+1 Zustände aus battery_state, Prozent im title", async ({ page }) => {
    await mockDevices(page, [
      makeDevice(1, "Batt-OK", "healthy", "ok", 80),
      makeDevice(2, "Batt-Warn", "healthy", "warn", 15),
      makeDevice(3, "Batt-Kritisch", "healthy", "kritisch", 5),
      makeDevice(4, "Batt-Unbekannt", "healthy", "unbekannt", null),
    ]);
    await page.goto("/devices?sort=label");

    const badges = page.getByTestId("device-battery-cell").getByTestId("battery-badge");
    await expect(badges).toHaveCount(4);
    // sort=label -> alphabetisch: Kritisch, OK, Unbekannt, Warn
    await expect(page.locator("tbody tr").nth(0).getByTestId("battery-badge")).toHaveAttribute(
      "data-battery",
      "kritisch",
    );
    // Prozent nur im title-Tooltip (5 % für das kritische Gerät).
    await expect(page.locator("tbody tr").nth(0).getByTestId("battery-badge")).toHaveAttribute(
      "title",
      "Batterie: 5 %",
    );
    // unbekannt ohne Reading -> Hint-title, keine Zahl.
    const unknownBadge = page
      .locator("tbody tr")
      .filter({ hasText: "Batt-Unbekannt" })
      .getByTestId("battery-badge");
    await expect(unknownBadge).toHaveAttribute("data-battery", "unbekannt");
  });

  test("statusScore: offline (silent) schlägt batt-kritisch (health-Achse > batt-Achse)", async ({
    page,
  }) => {
    // Scores: Offline-OK=4 (silent), Online-Kritisch=2, Online-Warn=1, Online-OK=0.
    await mockDevices(page, [
      makeDevice(10, "Online-OK", "healthy", "ok", 90),
      makeDevice(11, "Online-Warn", "healthy", "warn", 15),
      makeDevice(12, "Online-Kritisch", "healthy", "kritisch", 5),
      makeDevice(13, "Offline-OK", "silent", "ok", 90),
    ]);
    // Default-Sortierung = Fehlerstatus (kein ?sort).
    await page.goto("/devices");

    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(4);
    // Erwartete Reihenfolge absteigend nach Score: 4 > 2 > 1 > 0.
    await expect(rows.nth(0)).toContainText("Offline-OK"); // silent = 4 (schlägt kritisch=2)
    await expect(rows.nth(1)).toContainText("Online-Kritisch"); // batt-kritisch = 2
    await expect(rows.nth(2)).toContainText("Online-Warn"); // batt-warn = 1
    await expect(rows.nth(3)).toContainText("Online-OK"); // healthy+ok = 0
  });
});
