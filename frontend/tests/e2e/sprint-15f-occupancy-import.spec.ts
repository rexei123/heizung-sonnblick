import { expect, test, type Page } from "./fixtures";

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
  checkouts_changed?: number;
  result: "applied" | "rejected";
}

const KPI = {
  rooms_occupied: 1,
  rooms_total: 30,
  avg_temperature_celsius: 21.4,
  devices_online: 4,
  devices_assigned: 4,
  devices_pool: 0,
  active_overrides: 0,
  zones_window_open: 0,
  last_engine_tick: new Date(Date.now() - 60_000).toISOString(),
  battery_low_count: 0,
  valve_check_count: 0,
  room_too_warm_count: 0,
};

/**
 * `ExpectedByForm` rendert nur mit geladener Konfiguration (`if (!cfg.data)
 * return null`). Ohne diesen Mock bleibt der Hilfetext unsichtbar, und ein
 * Test darauf schlaegt an der falschen Stelle fehl — genau so ist es beim
 * ersten Lauf passiert.
 */
const GLOBAL_CONFIG = {
  id: 1,
  hotel_name: "Hotel Sonnblick",
  timezone: "Europe/Vienna",
  default_checkin_time: "14:00:00",
  default_checkout_time: "11:00:00",
  summer_mode_starts_on: null,
  summer_mode_ends_on: null,
  alert_email: "chef@hotel.example.com",
  alert_device_offline_minutes: 60,
  occupancy_import_expected_by_local: "12:00:00",
  created_at: "2026-10-21T06:00:00Z",
  updated_at: "2026-10-21T06:00:00Z",
  last_mail_attempt_at: null,
  last_mail_error: null,
};

function logPayload(partial: Record<string, unknown>): string {
  return JSON.stringify({
    status: "green",
    last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
    expected_by_local: "12:00",
    // Pflichtfeld im Zod-Schema. Fehlt es, scheitert das Parsen und die
    // Kachel rendert gar nicht — der Mock muss die Antwortform vollstaendig
    // abbilden (§5.64).
    expected_by_local_label: "12:00 MESZ",
    // Seit 21.10.2026: die gemessene Eingangszeit. `null` ist ein gültiger
    // Wert ("noch keine Liste"), deshalb hier ein Vorgabewert, den die
    // Tests einzeln überschreiben.
    first_list_local_label: "08:30 MESZ",
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
  await page.route(/.*\/api\/v1\/global-config(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GLOBAL_CONFIG),
    });
  });
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
      checkouts_changed: 2,
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

  test("Spalte „Abreise geändert\" zeigt die Zahl, fehlendes Feld bleibt 0", async ({
    page,
  }) => {
    // Die zweite und dritte Zeile liefern das Feld **nicht** — so sehen
    // Audit-Zeilen von vor dem 19.10.2026 aus. Das Zod-Schema setzt 0 ein;
    // ohne diese Vorgabe liefe das ganze Protokoll leer statt einer Spalte.
    await mockImport(page, { status: "yellow", imports: ROWS });
    await page.goto("/einstellungen/api");

    // Bewusst ``getByText`` und nicht ``getByRole("columnheader")``:
    // gemessen am 19.10.2026 meldet diese Seite **0** Spaltenkoepfe, fuer
    // alle sieben Spalten, nicht nur fuer diese. Den ``th``-Elementen fehlt
    // ``scope="col"`` (zurueckgestellter Punkt vom 15.10.). Die Ursache ist
    // noch nicht belegt — hier steht die Messung, keine Erklaerung.
    await expect(page.getByText("Abreise geändert")).toBeVisible();
    const zeilen = page.getByTestId("import-row");
    await expect(zeilen.nth(0).locator("td").nth(4)).toHaveText("2");
    await expect(zeilen.nth(1).locator("td").nth(4)).toHaveText("0");
  });

  test("Hilfetext nennt die **gemessene** Eingangszeit, nicht eine feste", async ({
    page,
  }) => {
    // Bis zum 20.10.2026 stand im Hilfetext „gegen 10:38". Mit dem
    // Mehrfachversand (08:30, 15:30, 19:30) war das falsch — und beim
    // nächsten Wechsel wäre es wieder falsch. Die Zahl kommt jetzt aus den
    // Daten der letzten sieben Tage.
    await mockImport(page, { status: "green", first_list_local_label: "08:30 MESZ" });
    await page.goto("/einstellungen/api");

    await expect(
      page.getByText(/Die erste Liste des Tages kam zuletzt gegen/),
    ).toBeVisible();
    await expect(page.getByText("08:30 MESZ")).toBeVisible();
    await expect(page.getByText(/10:38/)).toHaveCount(0);
  });

  test("ohne Liste in sieben Tagen steht der Satz ohne Lücke da", async ({ page }) => {
    // Der Zustand eines frisch aufgesetzten Systems. Ohne diesen Zweig
    // stünde dort „kam zuletzt gegen" und danach nichts.
    await mockImport(page, { status: "red", first_list_local_label: null });
    await page.goto("/einstellungen/api");

    await expect(page.getByText(/Bisher ist noch keine Liste eingetroffen/)).toBeVisible();
    await expect(page.getByText(/kam zuletzt gegen/)).toHaveCount(0);
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
