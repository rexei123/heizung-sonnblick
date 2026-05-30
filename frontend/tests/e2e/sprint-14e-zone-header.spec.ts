import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 14e T3 — ZoneCard-Header zeigt FU-1 Ist-Temp + FU-2 effektiven Setpoint.
 *
 * R1 Effektiver Setpoint: active_override > engine_setpoint_c > „—".
 * R2 None-State: ``null`` rendert als „—", nicht als ``0.0``.
 *
 * Backend gemockt via page.route (Pattern Sprint 14b/14d).
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
  has_active_override: false,
  notes: null,
  created_at: NOW,
  updated_at: NOW,
};

interface ZoneFixture {
  id: number;
  room_id: number;
  kind: "bedroom" | "bathroom" | "living" | "hallway" | "other";
  name: string;
  is_towel_warmer: boolean;
  health_state: "healthy" | "degraded" | "silent" | "no_device";
  created_at: string;
  updated_at: string;
  active_override?: {
    source: "device" | "frontend_4h" | "frontend_midnight" | "frontend_checkout";
    setpoint_celsius: number;
    started_at: string;
    expires_at: string;
  } | null;
  mean_temperature_c: number | null;
  engine_setpoint_c: number | null;
}

function makeZone(partial: Partial<ZoneFixture>): ZoneFixture {
  return {
    id: 201,
    room_id: 101,
    kind: "bedroom",
    name: "Schlafzimmer",
    is_towel_warmer: false,
    health_state: "healthy",
    created_at: NOW,
    updated_at: NOW,
    active_override: null,
    mean_temperature_c: null,
    engine_setpoint_c: null,
    ...partial,
  };
}

async function mockApi(page: Page, zone: ZoneFixture): Promise<void> {
  await page.route("**/api/v1/**", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/auth/me", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(MOCK_ADMIN) }),
  );
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ROOM) }),
  );
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([zone]) }),
  );
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
}

async function gotoZonenTab(page: Page): Promise<void> {
  await page.goto("/zimmer/101");
  await page.getByRole("button", { name: "Heizzonen", exact: true }).click();
}

test.describe("Sprint 14e — ZoneCard-Header (FU-1 + FU-2)", () => {
  test("Ist-Temp + Engine-Setpoint sichtbar, ohne Override", async ({ page }) => {
    await mockApi(
      page,
      makeZone({ mean_temperature_c: 21.4, engine_setpoint_c: 21.0 }),
    );
    await gotoZonenTab(page);

    const ist = page.getByTestId("zone-card-201-mean-temp");
    await expect(ist).toContainText("Ist-Temp");
    await expect(ist).toContainText("21.4 °C");

    const soll = page.getByTestId("zone-card-201-effective-setpoint");
    await expect(soll).toContainText("Soll");
    await expect(soll).toContainText("21.0 °C");

    // Ohne Override: kein Source-Badge im Soll-Slot.
    await expect(page.getByTestId("zone-card-201-soll-source")).toHaveCount(0);
  });

  test("Override-Setpoint hat Vorrang vor Engine-Setpoint (R1)", async ({ page }) => {
    await mockApi(
      page,
      makeZone({
        mean_temperature_c: 21.0,
        engine_setpoint_c: 21.0,
        active_override: {
          source: "frontend_4h",
          setpoint_celsius: 23.0,
          started_at: NOW,
          expires_at: FUTURE,
        },
      }),
    );
    await gotoZonenTab(page);

    const soll = page.getByTestId("zone-card-201-effective-setpoint");
    // Override-Wert (23.0) gewinnt, nicht engine_setpoint_c (21.0).
    await expect(soll).toContainText("23.0 °C");
    await expect(soll).not.toContainText("21.0 °C");

    // Source-Badge sichtbar (Gast/Mitarbeiter erkennbar).
    const src = page.getByTestId("zone-card-201-soll-source");
    await expect(src).toBeVisible();
    await expect(src).toContainText("4 Stunden (Mitarbeiter)");
  });

  test("Null-Werte rendern als Em-Dash (R2)", async ({ page }) => {
    await mockApi(
      page,
      makeZone({ mean_temperature_c: null, engine_setpoint_c: null }),
    );
    await gotoZonenTab(page);

    await expect(page.getByTestId("zone-card-201-mean-temp")).toContainText("—");
    await expect(page.getByTestId("zone-card-201-effective-setpoint")).toContainText(
      "—",
    );
    // Sicherheits-Check: kein "0.0 °C", das waere R2-Verstoss.
    await expect(page.getByTestId("zone-card-201-mean-temp")).not.toContainText(
      "0.0 °C",
    );
  });
});
