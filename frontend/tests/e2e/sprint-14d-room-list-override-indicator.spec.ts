import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 14d (R-A/R-B) — Playwright E2E fuer Aktiv-Indikator-Spalte in
 * Zimmer-Uebersicht.
 *
 * Backend gemockt via ``page.route`` (Pattern wie Sprint 12c.a). §5.54: RegExp
 * mit ``(\?.*)?$``. ZIMMER 101 entspricht dem Cowork-Setup (nicht aufraeumen).
 *
 * Drei exklusive Zustaende in EINER Zelle (R-B):
 *  1) ``guest_override_blocked === true`` -> Lock (Bestand Sprint 12c.a)
 *  2) sonst ``has_active_override === true`` -> "Aktiv"-Indikator (tune-Icon)
 *  3) sonst leer
 *
 * Pflicht: nie kombiniert (Lock-Zimmer zeigen NICHT zusaetzlich "Aktiv",
 * auch wenn has_active_override true ist — Lock gewinnt).
 */

const MOCK_MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  last_login_at: "2026-05-29T18:00:00Z",
};

function roomMock(
  id: number,
  number: string,
  opts: { blocked?: boolean; hasActiveOverride?: boolean } = {},
): Record<string, unknown> {
  return {
    id,
    number,
    display_name: null,
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: "occupied",
    guest_override_blocked: opts.blocked ?? false,
    has_active_override: opts.hasActiveOverride ?? false,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-05-29T10:00:00Z",
  };
}

async function mockApi(page: Page, rooms: Record<string, unknown>[]): Promise<void> {
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

test.describe("Sprint 14d — Aktiv-Indikator in Zimmer-Uebersicht", () => {
  test("Zimmer 101 mit aktivem Override zeigt 'Aktiv'", async ({ page }) => {
    await mockApi(page, [
      roomMock(101, "101", { hasActiveOverride: true }),
      roomMock(102, "102", { hasActiveOverride: false }),
    ]);
    await page.goto("/zimmer");

    const row101 = page.getByRole("row").filter({ hasText: "101" });
    const aktiv = row101.getByLabel("Übersteuerung aktiv");
    await expect(aktiv).toBeVisible();
    await expect(aktiv).toContainText("Aktiv");
    await expect(aktiv).toHaveAttribute("title", "Übersteuerung aktiv");

    const row102 = page.getByRole("row").filter({ hasText: "102" });
    await expect(row102.getByLabel("Übersteuerung aktiv")).toHaveCount(0);
    await expect(row102.getByLabel("Übersteuerung gesperrt")).toHaveCount(0);
  });

  test("Gesperrtes Zimmer zeigt Lock (R-B-Exklusivitaet: NICHT Aktiv)", async ({ page }) => {
    // R-B: Lock gewinnt gegen has_active_override — beide gleichzeitig
    // wird semantisch nicht kombiniert.
    await mockApi(page, [
      roomMock(201, "201", { blocked: true, hasActiveOverride: true }),
    ]);
    await page.goto("/zimmer");

    const row = page.getByRole("row").filter({ hasText: "201" });
    await expect(row.getByLabel("Übersteuerung gesperrt")).toBeVisible();
    await expect(row.getByLabel("Übersteuerung aktiv")).toHaveCount(0);
  });

  test("Zimmer ohne Override und ohne Sperre: leere Zelle", async ({ page }) => {
    await mockApi(page, [roomMock(301, "301")]);
    await page.goto("/zimmer");

    await expect(page.getByRole("row").filter({ hasText: "301" })).toBeVisible();
    await expect(page.getByLabel("Übersteuerung aktiv")).toHaveCount(0);
    await expect(page.getByLabel("Übersteuerung gesperrt")).toHaveCount(0);
  });
});
