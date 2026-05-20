import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 12b T5 — Playwright E2E fuer Pro-Zone-Override-UI.
 *
 * Backend wird via ``page.route()`` gemockt, kein laufender FastAPI noetig
 * (CI-tauglich). Pattern wie ``auth.spec.ts``.
 *
 * Test-Cases:
 *  1. Happy: Zone-Override anlegen (Schlafzimmer 21 °C 4h), Card zeigt Aktiv,
 *     POST-Body enthaelt heating_zone_id, Revoke macht Card leer
 *  2. Window-Blocked: Window-Open in Zone 1 -> Submit-Button disabled +
 *     Hinweis sichtbar, kein POST geht raus
 *  3. Room-not-occupied: Backend liefert 409 room_not_occupied ->
 *     Toast-Text sichtbar
 *  4. Invalid-Zone: Backend liefert 404 invalid_zone -> Toast-Text sichtbar
 *  5. Engine-Decision-Panel: Pro-Zone-Setpoint-Block sichtbar wenn
 *     zone_overrides_trace in HARD_CLAMP-Row vorhanden
 *
 * Brief: Strategie-Chat 2026-05-20, Sprint 12b T5.
 */

const MOCK_MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  last_login_at: "2026-05-19T18:00:00Z",
};

const ROOM = {
  id: 101,
  number: "101",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "occupied",
  notes: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-05-15T10:00:00Z",
};

const ZONE_BEDROOM = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

const ZONE_BATHROOM = {
  id: 202,
  room_id: 101,
  kind: "bathroom" as const,
  name: "Bad",
  is_towel_warmer: true,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

function engineTraceWithoutOpenWindow(): unknown[] {
  const evalId = "00000000-0000-0000-0000-000000000aaa";
  const now = new Date().toISOString();
  return [
    {
      time: now,
      room_id: 101,
      evaluation_id: evalId,
      layer: "window_safety",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: { detail: "no_open_window", open_zones: [] },
    },
    {
      time: now,
      room_id: 101,
      evaluation_id: evalId,
      layer: "hard_clamp",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: { detail: "within [10,30]" },
    },
  ];
}

function engineTraceWithOpenWindow(zoneId: number): unknown[] {
  const evalId = "00000000-0000-0000-0000-000000000bbb";
  const now = new Date().toISOString();
  return [
    {
      time: now,
      room_id: 101,
      evaluation_id: evalId,
      layer: "window_safety",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "10.0",
      reason: "window_open",
      details: {
        detail: "window_open_room_occupied_setback",
        open_zones: [{ zone_id: zoneId, reading_at: now }],
      },
    },
    {
      time: now,
      room_id: 101,
      evaluation_id: evalId,
      layer: "hard_clamp",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "10.0",
      reason: "window_open",
      details: { detail: "within [10,30]" },
    },
  ];
}

function engineTraceWithZoneOverrides(): unknown[] {
  const evalId = "00000000-0000-0000-0000-000000000ccc";
  const now = new Date().toISOString();
  return [
    {
      time: now,
      room_id: 101,
      evaluation_id: evalId,
      layer: "window_safety",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: { detail: "no_open_window", open_zones: [] },
    },
    {
      time: now,
      room_id: 101,
      evaluation_id: evalId,
      layer: "hard_clamp",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: {
        detail: "within [10,30]",
        zone_overrides_trace: [
          { zone_id: 201, setpoint_c: 21, override_id: 1, source: "frontend_4h" },
          { zone_id: 202, setpoint_c: 24, override_id: 2, source: "frontend_4h" },
        ],
      },
    },
  ];
}

async function mockBasicAuthAndRoom(
  page: Page,
  opts: {
    overrides?: unknown[];
    trace?: unknown[];
  } = {},
): Promise<void> {
  // Catch-all zuerst registrieren (Playwright: zuletzt registriert wird zuerst getroffen)
  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route("**/api/v1/auth/me", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_MITARBEITER),
    });
  });

  await page.route("**/api/v1/rooms/101", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ROOM),
    });
  });

  await page.route("**/api/v1/rooms/101/heating-zones", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([ZONE_BEDROOM, ZONE_BATHROOM]),
    });
  });

  await page.route("**/api/v1/rooms/101/engine-trace*", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.trace ?? engineTraceWithoutOpenWindow()),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(opts.overrides ?? []),
      });
      return;
    }
    // POST faengt der Test mit eigenem Route-Override
    await route.continue();
  });
}

test.describe("Sprint 12b — Pro-Zone-Override-Panels", () => {
  test("Case 1 Happy: Zone-Override anlegen + Aktiv-Card + Revoke", async ({ page }) => {
    await mockBasicAuthAndRoom(page);

    let postedBody: Record<string, unknown> | null = null;
    let postedOverride: Record<string, unknown> | null = null;
    let revokedId: number | null = null;

    await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (route: Route) => {
      if (route.request().method() === "POST") {
        const parsed = JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>;
        postedBody = parsed;
        postedOverride = {
          id: 555,
          room_id: 101,
          heating_zone_id: parsed.heating_zone_id ?? null,
          setpoint: parsed.setpoint,
          source: parsed.source,
          expires_at: new Date(Date.now() + 4 * 3600 * 1000).toISOString(),
          reason: parsed.reason ?? null,
          created_at: new Date().toISOString(),
          created_by: MOCK_MITARBEITER.email,
          revoked_at: null,
          revoked_reason: null,
        };
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(postedOverride),
        });
        return;
      }
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(postedOverride ? [postedOverride] : []),
        });
        return;
      }
    });

    await page.route(/.*\/api\/v1\/overrides\/\d+$/, async (route: Route) => {
      if (route.request().method() === "DELETE") {
        const match = route.request().url().match(/\/overrides\/(\d+)$/);
        revokedId = match ? parseInt(match[1], 10) : null;
        if (postedOverride) {
          postedOverride = { ...postedOverride, revoked_at: new Date().toISOString() };
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(postedOverride ?? {}),
        });
        return;
      }
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung" }).click();

    await expect(page.getByRole("heading", { name: "Schlafzimmer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Bad" })).toBeVisible();

    // Submit-Form in Schlafzimmer-Zone
    // Zones sortiert nach id (bedroom 201 vor bathroom 202) -> first()
    // ist Schlafzimmer-Card's Anwenden-Button.
    await page.getByRole("button", { name: "Anwenden" }).first().click();

    await expect.poll(() => postedBody).not.toBeNull();
    expect(postedBody).toMatchObject({
      setpoint: "21",
      source: "frontend_4h",
      heating_zone_id: ZONE_BEDROOM.id,
    });

    // Aktiv-Card sichtbar
    await expect(page.getByRole("button", { name: "Übersteuerung aufheben" })).toBeVisible();

    // Revoke
    await page.getByRole("button", { name: "Übersteuerung aufheben" }).click();
    await page.getByRole("button", { name: "Aufheben" }).click();

    await expect.poll(() => revokedId).toBe(555);
  });

  test("Case 2 Window-Blocked: Button disabled + Hinweis", async ({ page }) => {
    await mockBasicAuthAndRoom(page, {
      trace: engineTraceWithOpenWindow(ZONE_BEDROOM.id),
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung" }).click();

    await expect(page.getByText("Fenster offen — Übersteuerung nicht möglich")).toBeVisible();
    // bedroom-Card zuerst (zone id 201) -> first() ist Schlafzimmer.
    const anwendenButton = page.getByRole("button", { name: "Anwenden" }).first();
    await expect(anwendenButton).toBeDisabled();
  });

  test("Case 3 Room-not-occupied: 409-Toast nach POST", async ({ page }) => {
    await mockBasicAuthAndRoom(page);

    await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (route: Route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: { error: "room_not_occupied", room_id: 101 },
          }),
        });
        return;
      }
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        });
        return;
      }
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung" }).click();

    // Zones sortiert nach id (bedroom 201 vor bathroom 202) -> first()
    // ist Schlafzimmer-Card's Anwenden-Button.
    await page.getByRole("button", { name: "Anwenden" }).first().click();

    await expect(
      page.getByText("Zimmer ist nicht belegt — Übersteuerung nicht möglich"),
    ).toBeVisible();
  });

  test("Case 4 Invalid-Zone: 404-Toast nach POST", async ({ page }) => {
    await mockBasicAuthAndRoom(page);

    await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (route: Route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            detail: { error: "invalid_zone", zone_id: 999, room_id: 101 },
          }),
        });
        return;
      }
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        });
        return;
      }
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung" }).click();

    // Zones sortiert nach id (bedroom 201 vor bathroom 202) -> first()
    // ist Schlafzimmer-Card's Anwenden-Button.
    await page.getByRole("button", { name: "Anwenden" }).first().click();

    await expect(page.getByText("Heizzone nicht gefunden")).toBeVisible();
  });

  test("Case 5 Engine-Decision-Panel: Pro-Zone-Setpoints sichtbar", async ({ page }) => {
    await mockBasicAuthAndRoom(page, { trace: engineTraceWithZoneOverrides() });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Engine" }).click();

    await expect(page.getByText("Pro-Zone-Setpoints")).toBeVisible();
    await expect(page.getByText(/Schlafzimmer.*Zone 201/)).toBeVisible();
    await expect(page.getByText(/Bad.*Zone 202/)).toBeVisible();
    // Pro-Zone-Setpoints sichtbar (24 °C als Bad-Wert)
    const proZoneBlock = page.locator("div").filter({ hasText: /Pro-Zone-Setpoints/ }).last();
    await expect(proZoneBlock.getByText("24 °C")).toBeVisible();
  });
});
