import { test, expect, type Page } from "@playwright/test";

/**
 * Sprint 14a — ZoneHealthBadge (D6/D7).
 *
 * Vier Zustaende (healthy/degraded/silent/no_device) in beiden Varianten:
 * - compact: /devices-Liste (Status-Spalte)
 * - detailed: /devices/[id]-Detail-Header (Pille + Hint-Zeile)
 *
 * Quelle ist ``device.heating_zone.health_state`` aus dem Nested-Response
 * (kein eigener API-Call) — Backend gemockt via Route-Interception.
 */

const iso = (offsetMs = 0) => new Date(Date.now() - offsetMs).toISOString();

type ZoneHealth = "healthy" | "degraded" | "silent" | "no_device";

function makeDevice(id: number, health: ZoneHealth) {
  return {
    id,
    dev_eui: `00000000000000${id.toString().padStart(2, "0")}`,
    app_eui: null,
    kind: "thermostat",
    vendor: "mclimate",
    model: "vicki",
    label: `Thermostat-${id}`,
    heating_zone_id: id,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: iso(5 * 60 * 1000),
    firmware_version: "4.2",
    health_state: "healthy",
    created_at: iso(86400 * 1000),
    updated_at: iso(),
    hardware_number: null,
    heating_zone: {
      id,
      name: `Zone-${id}`,
      health_state: health,
      room: { id, number: `10${id}`, room_type: { id: 1, name: "Doppelzimmer" } },
    },
    active_override: null,
    latest_reading: null,
  };
}

const HW_STATUS = {
  status: "active",
  last_seen: iso(5 * 60 * 1000),
  frames_in_window: 3,
  window_minutes: 30,
};

async function mockHardwareStatus(page: Page) {
  await page.route("**/api/v1/devices/*/hardware-status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HW_STATUS) }),
  );
}

const LABELS: Record<ZoneHealth, string> = {
  healthy: "Zone OK",
  degraded: "Zone Achtung",
  silent: "Zone Stumm",
  no_device: "Kein Gerät",
};

test.describe("Sprint 14a — ZoneHealthBadge", () => {
  test("compact: alle 4 Zustaende in der /devices-Liste", async ({ page }) => {
    const devices = [
      makeDevice(1, "healthy"),
      makeDevice(2, "degraded"),
      makeDevice(3, "silent"),
      makeDevice(4, "no_device"),
    ];
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(devices),
      }),
    );
    await mockHardwareStatus(page);

    await page.goto("/devices");

    const badges = page.getByTestId("zone-health-badge");
    await expect(badges).toHaveCount(4);

    for (const state of ["healthy", "degraded", "silent", "no_device"] as ZoneHealth[]) {
      const byHealth = page.locator(`[data-testid="zone-health-badge"][data-health="${state}"]`);
      await expect(byHealth).toHaveCount(1);
      await expect(byHealth).toContainText(LABELS[state]);
    }
  });

  test("detailed: Detail-Header rendert Pille + Hint (silent)", async ({ page }) => {
    const device = makeDevice(3, "silent");
    await page.route(`**/api/v1/devices/${device.id}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(device),
      }),
    );
    await page.route(`**/api/v1/devices/${device.id}/sensor-readings*`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await mockHardwareStatus(page);

    await page.goto(`/devices/${device.id}`);

    const badge = page.getByTestId("zone-health-badge");
    await expect(badge).toHaveAttribute("data-health", "silent");
    await expect(badge).toContainText("Zone Stumm");
    // detailed-Variante zeigt zusaetzlich die Hint-Zeile.
    await expect(badge).toContainText("Alle Thermostate der Zone sind länger offline.");
  });
});
