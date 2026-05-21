import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 12c.a — Playwright E2E fuer Block-Indikator-Spalte in
 * Zimmer-Uebersicht.
 *
 * Backend wird via ``page.route()`` gemockt — Pattern wie
 * sprint12c-room-override-blocked.spec.ts. §5.54: RegExp-Routes mit
 * ``(\?.*)?$`` fuer Query-String-Robustheit (``useRooms`` ruft
 * ``/rooms?limit=200`` auf).
 *
 * Test-Cases (2):
 *  A) list_shows_lock_symbol_for_blocked_room — Zimmer 101 blocked,
 *     Zimmer 102 nicht: nur Zeile 101 traegt das Lock-Symbol mit
 *     aria-label/title "Uebersteuerung gesperrt".
 *  B) list_no_lock_symbol_when_all_rooms_unblocked — beide Zimmer
 *     ohne Sperre: keine Body-Zelle traegt das Lock-Symbol.
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

function roomMock(
  id: number,
  number: string,
  blocked: boolean,
): Record<string, unknown> {
  return {
    id,
    number,
    display_name: null,
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: "occupied",
    guest_override_blocked: blocked,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-05-15T10:00:00Z",
  };
}

async function mockApi(
  page: Page,
  rooms: Record<string, unknown>[],
): Promise<void> {
  // Catch-all (Playwright: zuletzt registriert wird zuerst getroffen).
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

  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 1,
          name: "Standard",
          beds: 2,
          area_m2: 20,
          occupied_setpoint: "21",
          vacant_setpoint: "18",
          night_setback_offset: "2",
          frost_protection_setpoint: "8",
          created_at: "2026-04-01T10:00:00Z",
          updated_at: "2026-04-01T10:00:00Z",
        },
      ]),
    });
  });

  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(rooms),
    });
  });
}

test.describe("Sprint 12c.a — Block-Indikator in Zimmer-Uebersicht", () => {
  test("list_shows_lock_symbol_for_blocked_room", async ({ page }) => {
    await mockApi(page, [
      roomMock(101, "101", true),
      roomMock(102, "102", false),
    ]);

    await page.goto("/zimmer");

    // Lock-Symbol via aria-label sichtbar fuer das geblockte Zimmer.
    const lockSymbols = page.getByLabel("Übersteuerung gesperrt");
    await expect(lockSymbols).toHaveCount(1);

    // Lock-Symbol gehoert in die Zeile von Zimmer 101 (nicht 102).
    const row101 = page.getByRole("row").filter({ hasText: "101" });
    await expect(row101.getByLabel("Übersteuerung gesperrt")).toBeVisible();

    const row102 = page.getByRole("row").filter({ hasText: "102" });
    await expect(row102.getByLabel("Übersteuerung gesperrt")).toHaveCount(0);

    // Symbol-Text "lock" + title-Attribut konsistent.
    const sym = row101.getByLabel("Übersteuerung gesperrt");
    await expect(sym).toHaveText("lock");
    await expect(sym).toHaveAttribute("title", "Übersteuerung gesperrt");
  });

  test("list_no_lock_symbol_when_all_rooms_unblocked", async ({ page }) => {
    await mockApi(page, [
      roomMock(201, "201", false),
      roomMock(202, "202", false),
    ]);

    await page.goto("/zimmer");

    // Beide Zeilen sichtbar (Sanity: Mock wurde angewandt).
    await expect(page.getByRole("row").filter({ hasText: "201" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "202" })).toBeVisible();

    // Kein Lock-Symbol in keiner Zeile.
    await expect(page.getByLabel("Übersteuerung gesperrt")).toHaveCount(0);
  });
});
