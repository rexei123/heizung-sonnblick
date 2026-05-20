import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 12c (AE-58) — Playwright E2E fuer Uebersteuerungs-Sperre pro Zimmer.
 *
 * Backend wird via ``page.route()`` gemockt, kein laufender FastAPI noetig.
 * Pattern wie ``manual-override-zone.spec.ts`` (Sprint 12b).
 * §5.54: Routes mit RegExp + ``(\?.*)?$`` fuer Query-String-Robustheit.
 *
 * Test-Cases (4):
 *  1. Toggle-On bei aktiven Overrides zeigt Confirm-Dialog
 *  2. Toggle-On revoked Overrides und blendet Create-Form aus
 *  3. Blockiertes Zimmer rendert Banner, Create-Form ist weg
 *  4. Toggle-Off stellt Create-Form wieder her
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

function roomMock(opts: { blocked: boolean }): Record<string, unknown> {
  return {
    id: 101,
    number: "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: "occupied",
    guest_override_blocked: opts.blocked,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-05-15T10:00:00Z",
  };
}

const ZONE_BEDROOM = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

function engineTrace(): unknown[] {
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
  ];
}

function activeOverride(): Record<string, unknown> {
  return {
    id: 555,
    room_id: 101,
    heating_zone_id: ZONE_BEDROOM.id,
    setpoint: "21",
    source: "frontend_4h",
    expires_at: new Date(Date.now() + 4 * 3600 * 1000).toISOString(),
    reason: null,
    created_at: new Date().toISOString(),
    created_by: MOCK_MITARBEITER.email,
    revoked_at: null,
    revoked_reason: null,
  };
}

/**
 * Mock-Setup. ``roomState`` haelt den Room-Stand veraenderbar pro Test
 * (Toggle-PATCH ueberschreibt ``guest_override_blocked``).
 *
 * §5.54-Compliance: RegExp-Routes + ``(\?.*)?$`` fuer GET-mit-Query.
 */
async function mockApi(
  page: Page,
  opts: {
    initialBlocked: boolean;
    initialOverrides: Record<string, unknown>[];
  },
): Promise<{
  patchedBlocked: () => boolean | null;
  resetOverrides: () => void;
}> {
  let currentRoom = roomMock({ blocked: opts.initialBlocked });
  let currentOverrides = [...opts.initialOverrides];
  let patchedBlockedValue: boolean | null = null;

  // Catch-all leer (Playwright: zuletzt registriert wird zuerst getroffen).
  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_MITARBEITER),
    });
  });

  // PATCH /rooms/101/override-block-state — MUSS vor /rooms/101 stehen,
  // weil Playwright zuletzt registriert zuerst trifft.
  await page.route(
    /.*\/api\/v1\/rooms\/101\/override-block-state(\?.*)?$/,
    async (route: Route) => {
      if (route.request().method() === "PATCH") {
        const body = JSON.parse(route.request().postData() ?? "{}") as { blocked: boolean };
        patchedBlockedValue = body.blocked;
        currentRoom = roomMock({ blocked: body.blocked });
        if (body.blocked) {
          // Auto-Revoke wie Backend.
          currentOverrides = currentOverrides.map((ov) => ({
            ...ov,
            revoked_at: new Date().toISOString(),
            revoked_reason: "room_override_blocked",
          }));
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(currentRoom),
        });
        return;
      }
      await route.continue();
    },
  );

  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentRoom),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([ZONE_BEDROOM]),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/engine-trace(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(engineTrace()),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (route: Route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(currentOverrides),
      });
      return;
    }
    await route.continue();
  });

  return {
    patchedBlocked: () => patchedBlockedValue,
    resetOverrides: () => {
      currentOverrides = [];
    },
  };
}

test.describe("Sprint 12c — Uebersteuerungs-Sperre", () => {
  test("block_toggle_on_with_active_overrides_shows_confirm_dialog", async ({ page }) => {
    const ctrl = await mockApi(page, {
      initialBlocked: false,
      initialOverrides: [activeOverride()],
    });

    await page.goto("/zimmer/101");

    // Header zeigt Sperr-Button im Off-State.
    const toggleBtn = page.getByRole("button", { name: "Uebersteuerung sperren" });
    await expect(toggleBtn).toBeVisible();
    await toggleBtn.click();

    // Confirm-Dialog mit Count.
    await expect(page.getByText(/1 aktive Uebersteuerung wird/)).toBeVisible();

    // Cancel -> kein PATCH.
    await page.getByRole("button", { name: "Abbrechen" }).click();
    expect(ctrl.patchedBlocked()).toBeNull();
  });

  test("block_toggle_on_revokes_overrides_and_hides_create_form", async ({ page }) => {
    const ctrl = await mockApi(page, {
      initialBlocked: false,
      initialOverrides: [],
    });

    await page.goto("/zimmer/101");
    // Override-Tab oeffnen — Create-Form muss vor Toggle-On sichtbar sein.
    await page.getByRole("button", { name: "Übersteuerung" }).click();
    await expect(page.getByRole("button", { name: "Anwenden" })).toBeVisible();

    // Toggle-On (keine aktiven Overrides -> kein Dialog, direkter PATCH).
    await page
      .getByRole("button", { name: "Uebersteuerung sperren" })
      .click();

    // PATCH ging mit blocked=true raus.
    await expect.poll(() => ctrl.patchedBlocked()).toBe(true);

    // Banner sichtbar, Create-Form weg.
    await expect(page.getByText("Übersteuerung gesperrt").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Anwenden" })).toHaveCount(0);
  });

  test("blocked_room_create_form_hidden_banner_visible", async ({ page }) => {
    await mockApi(page, {
      initialBlocked: true,
      initialOverrides: [],
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung" }).click();

    // Banner + Hinweis-Text in Zone-Card; KEIN Anwenden-Button.
    await expect(page.getByText("Übersteuerung gesperrt").first()).toBeVisible();
    await expect(
      page.getByText("Übersteuerung gesperrt — bitte Mitarbeiter aufheben."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Anwenden" })).toHaveCount(0);

    // Toggle-Button im On-State.
    await expect(
      page.getByRole("button", { name: "Uebersteuerung freigeben" }),
    ).toBeVisible();
  });

  test("block_toggle_off_restores_create_form", async ({ page }) => {
    const ctrl = await mockApi(page, {
      initialBlocked: true,
      initialOverrides: [],
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Übersteuerung" }).click();
    await expect(page.getByRole("button", { name: "Anwenden" })).toHaveCount(0);

    // Toggle-Off — direkt ohne Confirm.
    await page
      .getByRole("button", { name: "Uebersteuerung freigeben" })
      .click();

    await expect.poll(() => ctrl.patchedBlocked()).toBe(false);

    // Create-Form wieder da.
    await expect(page.getByRole("button", { name: "Anwenden" })).toBeVisible();
    // Banner weg.
    await expect(page.getByText("Übersteuerung gesperrt — bitte Mitarbeiter aufheben.")).toHaveCount(0);
  });
});
