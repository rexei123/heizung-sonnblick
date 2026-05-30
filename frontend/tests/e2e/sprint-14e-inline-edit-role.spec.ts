import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 14e T5 — Inline-Edit Stammdaten mit Role-Affordance + Confirm.
 *
 * R5 Affordance-Gating: ``user.role === "admin"`` -> Edit-Pfade sichtbar;
 * ``mitarbeiter`` -> Read-only Anzeige.
 * room_type-Edit zeigt ConfirmDialog mit Engine-Wirkungs-Warnung; Zone-Name-
 * Edit nicht.
 */

const NOW = new Date().toISOString();

const ROOM_TYPES = [
  {
    id: 1,
    name: "Doppelzimmer",
    beds: 2,
    area_m2: 20,
    occupied_setpoint: "21",
    vacant_setpoint: "18",
    night_setback_offset: "2",
    frost_protection_setpoint: "8",
    created_at: NOW,
    updated_at: NOW,
  },
  {
    id: 2,
    name: "Suite",
    beds: 2,
    area_m2: 35,
    occupied_setpoint: "22",
    vacant_setpoint: "18",
    night_setback_offset: "2",
    frost_protection_setpoint: "8",
    created_at: NOW,
    updated_at: NOW,
  },
];

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

const ZONE = {
  id: 201,
  room_id: 101,
  kind: "bedroom",
  name: "Schlafzimmer",
  is_towel_warmer: false,
  health_state: "healthy",
  created_at: NOW,
  updated_at: NOW,
  active_override: null,
  mean_temperature_c: 21.0,
  engine_setpoint_c: 21.0,
};

interface MockOpts {
  role: "admin" | "mitarbeiter";
  patchRoomCalls?: { n: number; lastBody?: Record<string, unknown> };
  patchZoneCalls?: { n: number; lastBody?: Record<string, unknown> };
}

async function mockApi(page: Page, opts: MockOpts): Promise<void> {
  const user = {
    id: 99,
    email: `${opts.role}@hotel.example.com`,
    role: opts.role,
    is_active: true,
    must_change_password: false,
    created_at: NOW,
    updated_at: NOW,
    last_login_at: NOW,
  };

  await page.route("**/api/v1/**", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/auth/me", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(user) }),
  );
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ROOM_TYPES),
    }),
  );
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, async (route: Route) => {
    const method = route.request().method();
    if (method === "PATCH" && opts.patchRoomCalls) {
      opts.patchRoomCalls.n += 1;
      opts.patchRoomCalls.lastBody = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...ROOM, ...opts.patchRoomCalls.lastBody }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ROOM),
    });
  });
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([ZONE]) }),
  );
  await page.route(
    /.*\/api\/v1\/rooms\/101\/heating-zones\/201(\?.*)?$/,
    async (route: Route) => {
      const method = route.request().method();
      if (method === "PATCH" && opts.patchZoneCalls) {
        opts.patchZoneCalls.n += 1;
        opts.patchZoneCalls.lastBody = route.request().postDataJSON() as Record<string, unknown>;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...ZONE, ...opts.patchZoneCalls.lastBody }),
        });
      }
      return route.fallback();
    },
  );
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
}

test.describe("Sprint 14e T5 — Inline-Edit Role-Gating + Confirm", () => {
  test("Admin sieht Edit-Affordance fuer Zone-Name und room_type", async ({ page }) => {
    await mockApi(page, { role: "admin" });
    await page.goto("/zimmer/101");

    // room_type-Editor: Select sichtbar.
    await expect(page.getByTestId("room-type-inline-select")).toBeVisible();
    await expect(page.getByTestId("room-type-inline-current")).toContainText(
      "Doppelzimmer",
    );

    // Zone-Tab: Zone-Name als Klickbarer Button.
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();
    await expect(page.getByTestId("zone-card-201-name-edit")).toBeVisible();
    await expect(page.getByTestId("zone-card-201-name-readonly")).toHaveCount(0);
  });

  test("Mitarbeiter sieht read-only Stammdaten", async ({ page }) => {
    await mockApi(page, { role: "mitarbeiter" });
    await page.goto("/zimmer/101");

    // room_type-Editor: nur Anzeige, kein Select.
    await expect(page.getByTestId("room-type-inline-current")).toContainText(
      "Doppelzimmer",
    );
    await expect(page.getByTestId("room-type-inline-select")).toHaveCount(0);

    // Zone-Tab: Zone-Name als read-only h3.
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();
    await expect(page.getByTestId("zone-card-201-name-readonly")).toBeVisible();
    await expect(page.getByTestId("zone-card-201-name-edit")).toHaveCount(0);
  });

  test("room_type-Wechsel zeigt ConfirmDialog mit Engine-Warnung", async ({ page }) => {
    const calls = { n: 0 };
    await mockApi(page, { role: "admin", patchRoomCalls: calls });
    await page.goto("/zimmer/101");

    await page.getByTestId("room-type-inline-select").selectOption({ value: "2" });

    // Confirm sichtbar, Wording enthaelt Engine-Tick-Warnung.
    await expect(page.getByRole("heading", { name: "Raumtyp ändern?" })).toBeVisible();
    await expect(page.getByText(/Heizverhalten ändert sich beim nächsten Engine-Tick/)).toBeVisible();

    // Vor dem Confirm darf KEIN PATCH abgesendet worden sein.
    expect(calls.n).toBe(0);

    await page.getByRole("button", { name: "Raumtyp ändern", exact: true }).click();
    await expect.poll(() => calls.n).toBe(1);
  });

  test("Zone-Name-Edit zeigt KEIN Confirm (kein Warning)", async ({ page }) => {
    const calls = { n: 0 };
    await mockApi(page, { role: "admin", patchZoneCalls: calls });
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    await page.getByTestId("zone-card-201-name-edit").click();
    const input = page.getByTestId("zone-card-201-name-input");
    await expect(input).toBeVisible();
    await input.fill("Schlafzimmer Neu");
    await input.press("Enter");

    // PATCH direkt ohne Confirm.
    await expect.poll(() => calls.n).toBe(1);
    await expect(page.getByRole("heading", { name: "Raumtyp ändern?" })).toHaveCount(0);
  });
});
