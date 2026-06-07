import { expect, test, type Page } from "@playwright/test";

/**
 * Sprint 15f (AE-66) — Belegungs-Import-Sichtbarkeit.
 *
 * Backend gemockt via page.route. Dashboard-Kachel "Belegungsliste" (Ampel
 * strikt aus ``status``) + Detailseite (/einstellungen/api, Importtabelle).
 */

interface ImportRow {
  received_at: string;
  list_date: string;
  external_id: string;
  rooms_occupied: number;
  rooms_closed: number;
  conflicts: number;
  result: "applied" | "rejected";
}

const KPI = {
  rooms_occupied: 1,
  rooms_total: 30,
  avg_temperature_celsius: 21.4,
  devices_online: 4,
  devices_total: 4,
  active_overrides: 0,
  zones_window_open: 0,
  last_engine_tick: new Date(Date.now() - 60_000).toISOString(),
  battery_low_count: 0,
};

function logPayload(partial: Record<string, unknown>): string {
  return JSON.stringify({
    status: "green",
    last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
    expected_by_local: "09:00",
    today_received: true,
    imports: [],
    ...partial,
  });
}

async function mockKpi(page: Page): Promise<void> {
  await page.route("**/api/v1/dashboard/kpi", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(KPI) });
  });
}

async function mockImport(page: Page, partial: Record<string, unknown>): Promise<void> {
  await page.route("**/api/v1/integrations/occupancy-import/log", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: logPayload(partial),
    });
  });
}

function importCard(page: Page) {
  return page.getByTestId("kpi-card").filter({ hasText: "Belegungsliste" });
}

test.describe("Sprint 15f Belegungsliste-Kachel (Dashboard)", () => {
  test("status green -> success-Tone (text-success)", async ({ page }) => {
    await mockKpi(page);
    await mockImport(page, { status: "green" });
    await page.goto("/");
    await expect(importCard(page)).toBeVisible();
    await expect(importCard(page).locator(".text-success")).toHaveCount(1);
  });

  test("status yellow -> warning-Tone (text-warning)", async ({ page }) => {
    await mockKpi(page);
    await mockImport(page, { status: "yellow", today_received: false });
    await page.goto("/");
    await expect(importCard(page).locator(".text-warning")).toHaveCount(1);
  });

  test("status red -> danger-Tone (text-danger)", async ({ page }) => {
    await mockKpi(page);
    await mockImport(page, {
      status: "red",
      today_received: false,
      last_success_at: new Date(Date.now() - 48 * 3_600_000).toISOString(),
    });
    await page.goto("/");
    await expect(importCard(page).locator(".text-danger")).toHaveCount(1);
  });

  test("last_success_at null -> 'Noch nie'", async ({ page }) => {
    await mockKpi(page);
    await mockImport(page, { status: "red", today_received: false, last_success_at: null });
    await page.goto("/");
    await expect(importCard(page)).toContainText("Noch nie");
  });

  test("Klick auf die Kachel führt zu /einstellungen/api", async ({ page }) => {
    await mockKpi(page);
    await mockImport(page, { status: "green" });
    await page.goto("/");
    await importCard(page).click();
    await expect(page).toHaveURL(/\/einstellungen\/api$/);
  });
});

test.describe("Sprint 15f Import-Detailseite (/einstellungen/api)", () => {
  const ROWS: ImportRow[] = [
    {
      received_at: "2026-06-06T05:14:15+00:00",
      list_date: "2026-06-06",
      external_id: "ok-1",
      rooms_occupied: 4,
      rooms_closed: 1,
      conflicts: 0,
      result: "applied",
    },
    {
      received_at: "2026-06-05T05:14:15+00:00",
      list_date: "2026-06-05",
      external_id: "conf-1",
      rooms_occupied: 3,
      rooms_closed: 0,
      conflicts: 2,
      result: "applied",
    },
    {
      received_at: "2026-06-04T05:14:15+00:00",
      list_date: "2026-06-04",
      external_id: "rej-1",
      rooms_occupied: 0,
      rooms_closed: 0,
      conflicts: 0,
      result: "rejected",
    },
  ];

  test("Tabelle gefüllt, neueste zuerst, Kalendertag ohne Shift", async ({ page }) => {
    await mockImport(page, { status: "yellow", imports: ROWS });
    await page.goto("/einstellungen/api");
    await expect(page.getByTestId("import-row")).toHaveCount(3);
    // Kalendertag rein als String formatiert (kein UTC-Shift) -> exakt "06.06.2026"
    // in der list_date-Spalte (die received_at-Zelle ist "06.06.2026, 07:14").
    await expect(page.getByText("06.06.2026", { exact: true })).toBeVisible();
    await expect(page.getByText("Übernommen")).toHaveCount(2);
    await expect(page.getByText("Abgewiesen")).toHaveCount(1);
  });

  test("rejected ODER conflicts>0 werden hervorgehoben (bg-warning-soft)", async ({ page }) => {
    await mockImport(page, { status: "yellow", imports: ROWS });
    await page.goto("/einstellungen/api");
    // Konflikt-Zeile + Rejected-Zeile = 2 hervorgehoben, die saubere nicht.
    await expect(page.locator("[data-testid=import-row].bg-warning-soft")).toHaveCount(2);
  });

  test("leere imports -> Leer-Hinweis", async ({ page }) => {
    await mockImport(page, { status: "green", imports: [] });
    await page.goto("/einstellungen/api");
    await expect(page.getByText("Noch keine Importe vorhanden.")).toBeVisible();
  });

  test("Endpoint-Fehler -> Fallback-Hinweis statt Crash", async ({ page }) => {
    await page.route("**/api/v1/integrations/occupancy-import/log", async (route) => {
      await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
    });
    await page.goto("/einstellungen/api");
    await expect(page.getByText("Import-Status nicht verfügbar.")).toBeVisible();
  });
});
