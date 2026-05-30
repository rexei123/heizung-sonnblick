import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 14b T8 — Zone-Karten im Heizzonen-Tab (/zimmer/[id]).
 *
 * Backend gemockt via page.route (Pattern Sprint 13b.2). §5.54 Regex-URLs.
 * Deckt: ZoneCard-Render, ZoneHealthBadge, ThermostatBubble (Ist-Temp +
 * Batterie aus latest_reading), read-only Override-Banner, Tab-Wechsel-CTA
 * (Link-out), Zone-Löschen, Create-Form. Plus Bestand-Smokes
 * (Übersteuerung-Tab + Geräte-Tab unverändert).
 */

const NOW = new Date().toISOString();
const FUTURE = new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString();

const MOCK_ADMIN = {
  id: 1,
  email: "admin@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: NOW,
  updated_at: NOW,
  last_login_at: NOW,
};

const ROOM = {
  id: 101,
  number: "101",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "occupied",
  guest_override_blocked: false,
  notes: null,
  created_at: NOW,
  updated_at: NOW,
};

interface ZoneActiveOverrideFixture {
  source: "device" | "frontend_4h" | "frontend_midnight" | "frontend_checkout";
  setpoint_celsius: number;
  started_at: string;
  expires_at: string;
}

interface ZoneFixture {
  id: number;
  room_id: number;
  kind: "bedroom" | "bathroom" | "living" | "hallway" | "other";
  name: string;
  is_towel_warmer: boolean;
  health_state: "healthy" | "degraded" | "silent" | "no_device";
  created_at: string;
  updated_at: string;
  // Sprint 14d FU-5: HeatingZoneRead.active_override (ersetzt useZoneOverride).
  active_override?: ZoneActiveOverrideFixture | null;
}

const ZONE: ZoneFixture = {
  id: 201,
  room_id: 101,
  kind: "bedroom",
  name: "Schlafzimmer",
  is_towel_warmer: false,
  health_state: "degraded",
  created_at: NOW,
  updated_at: NOW,
};

function makeDevice(activeOverride: unknown = null) {
  return {
    id: 42,
    dev_eui: "aabbccddeeff0011",
    app_eui: null,
    kind: "thermostat" as const,
    vendor: "mclimate" as const,
    model: "vicki",
    label: "Vicki-Schlafzimmer",
    heating_zone_id: ZONE.id,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: NOW,
    firmware_version: "4.2",
    health_state: "healthy" as const,
    created_at: NOW,
    updated_at: NOW,
    hardware_number: null,
    heating_zone: {
      id: ZONE.id,
      name: ZONE.name,
      health_state: ZONE.health_state,
      room: { id: 101, number: "101", room_type: { id: 1, name: "Doppelzimmer" } },
    },
    active_override: activeOverride,
    latest_reading: {
      valve_position: 42,
      open_window: false,
      attached_backplate: true,
      temperature: 21.0,
      battery_percent: 80,
      recorded_at: NOW,
    },
  };
}

const HW_STATUS = { status: "active" as const, last_seen: NOW, frames_in_window: 3, window_minutes: 30 };

// Sprint 14d FU-5: aktiver Zone-Override jetzt aus HeatingZoneRead.active_override.
// Form spiegelt DeviceActiveOverride (setpoint_celsius: number, expires_at: ISO).
const ZONE_ACTIVE_OVERRIDE: ZoneActiveOverrideFixture = {
  source: "frontend_4h",
  setpoint_celsius: 21,
  started_at: NOW,
  expires_at: FUTURE,
};

/**
 * Mock-Skelett. ``zonesRef`` ist eine mutable Liste (stateful für
 * Create/Delete). ``devices`` ist die Geräte-Liste der Zone.
 */
async function mockZonen(
  page: Page,
  opts: { zonesRef: { current: ZoneFixture[] }; devices: unknown[] },
): Promise<void> {
  await page.route("**/api/v1/**", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/auth/me", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_ADMIN) }),
  );
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ROOM) }),
  );
  // Heizzonen: GET (stateful), POST (create), DELETE (über Sub-Route).
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, async (route: Route) => {
    const method = route.request().method();
    if (method === "POST") {
      const body = route.request().postDataJSON() as { name: string; kind: string };
      const created: ZoneFixture = {
        ...ZONE,
        id: 202,
        name: body.name,
        kind: body.kind as ZoneFixture["kind"],
        is_towel_warmer: false,
        health_state: "no_device",
      };
      opts.zonesRef.current = [...opts.zonesRef.current, created];
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created) });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.zonesRef.current),
    });
  });
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones\/\d+(\?.*)?$/, async (route: Route) => {
    if (route.request().method() === "DELETE") {
      const m = route.request().url().match(/heating-zones\/(\d+)/);
      const zid = m ? Number(m[1]) : -1;
      opts.zonesRef.current = opts.zonesRef.current.filter((z) => z.id !== zid);
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fallback();
  });
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(opts.devices) }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HW_STATUS) }),
  );
}

async function gotoZonenTab(page: Page): Promise<void> {
  await page.goto("/zimmer/101");
  await page.getByRole("button", { name: "Heizzonen", exact: true }).click();
}

test.describe("Sprint 14b — Zone-Karten Heizzonen-Tab", () => {
  test("1+2 ZoneCard + ZoneHealthBadge im Header", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await gotoZonenTab(page);
    await expect(page.getByTestId("zone-card-201")).toBeVisible();
    const badge = page.getByTestId("zone-card-201").getByTestId("zone-health-badge");
    await expect(badge).toHaveAttribute("data-health", "degraded");
  });

  test("3 ThermostatBubble mit Ist-Temp + Batterie aus latest_reading", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await gotoZonenTab(page);
    const bubble = page.getByTestId("thermostat-bubble-42");
    await expect(bubble).toBeVisible();
    await expect(bubble).toContainText("21.0 °C");
    await expect(bubble).toContainText("80");
  });

  test("4 Read-only Override-Banner bei aktivem Override (FU-5)", async ({ page }) => {
    // Sprint 14d FU-5: ZoneCard liest aktiven Override direkt aus
    // HeatingZoneRead.active_override — KEIN separater /overrides-Roundtrip.
    const overridesCalls = { n: 0 };
    await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, (route: Route) => {
      overridesCalls.n += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    const zoneWithOverride: ZoneFixture = { ...ZONE, active_override: ZONE_ACTIVE_OVERRIDE };
    await mockZonen(page, { zonesRef: { current: [zoneWithOverride] }, devices: [makeDevice()] });
    await gotoZonenTab(page);
    const banner = page.getByTestId("zone-card-201-override-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("°C");
    await expect(banner).toContainText("läuft bis");
    // FU-5-Beleg: kein useZoneOverride-Aufruf mehr.
    expect(overridesCalls.n).toBe(0);
  });

  test("5 CTA Wunschtemperatur setzen wechselt auf Übersteuerung-Tab", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await gotoZonenTab(page);
    await page.getByTestId("zone-card-201-set-override-cta").click();
    // Übersteuerung-Tab rendert ManualOverrideZoneCard mit CreateOverrideForm.
    await expect(
      page.getByText("Engine arbeitet nach den regulären Regeln"),
    ).toBeVisible();
    await expect(page.getByTestId("zone-card-201")).toHaveCount(0);
  });

  test("6 Zone löschen → Confirm → Zone weg", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await gotoZonenTab(page);
    await page.getByTestId("zone-card-201-delete-button").click();
    await page.getByRole("button", { name: "Endgültig löschen", exact: true }).click();
    await expect(page.getByTestId("zone-card-201")).toHaveCount(0);
  });

  test("7 Create-Form legt neue Zone an → erscheint als ZoneCard", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await gotoZonenTab(page);
    await page.getByPlaceholder("Name (z.B. Schlafzimmer)").fill("Bad");
    await page.getByRole("button", { name: "Hinzufügen", exact: true }).click();
    await expect(page.getByTestId("zone-card-202")).toBeVisible();
  });

  test("Smoke: Übersteuerung-Tab rendert unverändert", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung", exact: true }).click();
    await expect(
      page.getByText("Engine arbeitet nach den regulären Regeln"),
    ).toBeVisible();
  });

  test("Smoke: Geräte-Tab unverändert (DevicesInRoom + Replace-Dialog)", async ({ page }) => {
    await mockZonen(page, { zonesRef: { current: [ZONE] }, devices: [makeDevice()] });
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();
    await expect(page.getByText("Vicki-Schlafzimmer")).toBeVisible();
    await page.getByRole("button", { name: "Thermostat tauschen", exact: true }).click();
    await expect(page.getByRole("button", { name: "Tauschen", exact: true })).toBeVisible();
  });
});
