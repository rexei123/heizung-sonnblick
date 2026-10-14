import { expect, test } from "@playwright/test";

/**
 * Sprint 14c T7 — Frontend-Tests fuer das Dashboard ("/").
 *
 * Backend gemockt via page.route. /api/v1/auth/me wird NICHT gemockt
 * (-> user null -> Begruessung "Hallo!"), das reicht fuer die KPI-Tests.
 */

interface Kpi {
  rooms_occupied: number;
  rooms_total: number;
  avg_temperature_celsius: number | null;
  devices_online: number;
  // Sprint 21 (B-21-2): Zod verlangt die beiden; `devices_total` gibt es
  // nicht mehr.
  devices_assigned: number;
  devices_pool: number;
  active_overrides: number;
  zones_window_open: number;
  last_engine_tick: string | null;
  // Sprint 15d (AE-65): Zod verlangt den Key jetzt — ohne ihn wirft parse.
  battery_low_count: number;
  // Sprint 20e (T7/T10): Zod verlangt diese beiden ebenfalls.
  valve_check_count: number;
  room_too_warm_count: number;
}

const BASE_KPI: Kpi = {
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

async function mockKpi(
  page: import("@playwright/test").Page,
  payload: Partial<Kpi>,
  counter?: { n: number },
): Promise<void> {
  await page.route("**/api/v1/dashboard/kpi", async (route) => {
    if (counter) counter.n += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...BASE_KPI, ...payload }),
    });
  });
}

test.describe("Sprint 14c Dashboard", () => {
  // Sprint 15f (AE-66): 8. Kachel „Belegungsliste" hat eine eigene Datenquelle
  // (GET .../occupancy-import/log). Ohne Mock liefe sie in den Error-State,
  // zählte aber weiter als kpi-card -> hier deterministisch grün mocken.
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/integrations/occupancy-import/log", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "green",
          last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
          expected_by_local: "12:00",
          expected_by_local_label: "12:00 MESZ",
          today_received: true,
          imports: [],
        }),
      });
    });
  });

  test("rendert 10 KPI-Kacheln", async ({ page }) => {
    await mockKpi(page, {});
    await page.goto("/");
    await expect(page.getByText("Belegte Zimmer")).toBeVisible();
    // Sprint 15d: „Schwache Batterie" (7.), Sprint 15f: „Belegungsliste" (8.),
    // Sprint 20e: „Ventil prüfen" (9.) und „Zimmer zu warm" (10.).
    //
    // Dass dieser Test bei jeder neuen Kachel fällt, ist sein Zweck: das
    // Dashboard ist die Seite, die der Hotelier täglich liest, und eine
    // Kachel mehr ist eine Entscheidung, keine Nebenwirkung.
    await expect(page.getByTestId("kpi-card")).toHaveCount(10);
  });

  test("Schwache-Batterie-Kachel: battery_low_count, warning-soft wenn > 0", async ({ page }) => {
    await mockKpi(page, { battery_low_count: 3 });
    await page.goto("/");
    const card = page.getByTestId("kpi-card").filter({ hasText: "Schwache Batterie" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("3");
  });

  test("Sprint 20e: Ventil-prüfen-Kachel zählt valve_check_count (beide Ventil-Befunde)", async ({ page }) => {
    await mockKpi(page, { valve_check_count: 2 });
    await page.goto("/");
    const card = page.getByTestId("kpi-card").filter({ hasText: "Ventil prüfen" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("2");
  });

  test("Sprint 20e: Zimmer-zu-warm-Kachel zählt room_too_warm_count", async ({ page }) => {
    // Das ist der Ersatz-Melder für Engine-Layer 4 Detached, den 20e T4
    // stillgelegt hat — ein Ventil ohne Kopf steht offen, das Zimmer wird
    // heiß. Die Kachel ist die einzige Stelle, an der das auffällt, solange
    // niemand die Geräteliste durchsieht.
    await mockKpi(page, { room_too_warm_count: 1 });
    await page.goto("/");
    const card = page.getByTestId("kpi-card").filter({ hasText: "Zimmer zu warm" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("1");
  });

  test("zeigt eine Begruessung", async ({ page }) => {
    await mockKpi(page, {});
    await page.goto("/");
    await expect(
      page.getByRole("heading", { level: 1, name: /Guten (Morgen|Tag|Abend)|Hallo/ }),
    ).toBeVisible();
  });

  test("refetcht nach 60 s erneut /api/v1/dashboard/kpi", async ({ page }) => {
    await page.clock.install();
    const counter = { n: 0 };
    await mockKpi(page, {}, counter);
    await page.goto("/");
    await expect(page.getByText("Belegte Zimmer")).toBeVisible();
    await expect.poll(() => counter.n).toBeGreaterThanOrEqual(1);
    const before = counter.n;
    await page.clock.runFor(61_000);
    await expect.poll(() => counter.n).toBeGreaterThan(before);
  });

  test("Mobile 390px: Kacheln einspaltig gestapelt", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockKpi(page, {});
    await page.goto("/");
    const cards = page.getByTestId("kpi-card");
    await expect(cards).toHaveCount(10);
    // Einspaltig: alle Karten teilen dieselbe linke Kante (gleiche x).
    const box0 = await cards.nth(0).boundingBox();
    const box1 = await cards.nth(1).boundingBox();
    expect(box0).not.toBeNull();
    expect(box1).not.toBeNull();
    expect(Math.abs((box0?.x ?? 0) - (box1?.x ?? 0))).toBeLessThan(2);
    // Zweite Karte liegt UNTER der ersten (gestapelt, nicht nebeneinander).
    expect(box1?.y ?? 0).toBeGreaterThan((box0?.y ?? 0) + 10);
  });

  test("Empty-State: avg null -> Karte zeigt Strich statt NaN", async ({ page }) => {
    await mockKpi(page, { avg_temperature_celsius: null });
    await page.goto("/");
    const tempCard = page.getByTestId("kpi-card").filter({ hasText: "Ø Raumtemperatur" });
    await expect(tempCard).toBeVisible();
    await expect(tempCard).not.toContainText("NaN");
    await expect(tempCard).toContainText("–");
  });

  test("devices_online < devices_assigned -> warning-Tone auf der Geraete-Kachel", async ({
    page,
  }) => {
    await mockKpi(page, { devices_online: 3, devices_assigned: 4 });
    await page.goto("/");
    const deviceCard = page.getByTestId("kpi-card").filter({ hasText: "Geräte online" });
    await expect(deviceCard).toBeVisible();
    await expect(deviceCard).toContainText("3");
    // Warning-Tone: Icon-Slot traegt text-warning.
    await expect(deviceCard.locator(".text-warning")).toHaveCount(1);
  });

  /**
   * Sprint 21 (B-21-2) — die drei Zusagen der Kachel.
   *
   * Vorher zaehlte der Nenner Pool und Lager mit: aus "101 von 101" wurde
   * "101 von 104", und weil ein Ersatzteil ohne Batterie korrekt "nicht
   * online" ist, stand die Kachel **dauerhaft** auf Gelb. Eine Warnung, die
   * immer leuchtet, warnt nicht (§5.79).
   */
  test("lager_steht_in_eigener_zeile_und_faerbt_die_kachel_nicht", async ({ page }) => {
    await mockKpi(page, { devices_online: 101, devices_assigned: 101, devices_pool: 3 });
    await page.goto("/");
    const deviceCard = page.getByTestId("kpi-card").filter({ hasText: "Geräte online" });

    await expect(deviceCard).toContainText("von 101");
    await expect(deviceCard).toContainText("3 im Lager");
    // Entscheidend: kein Warning-Tone. Das Lager ist ein Normalzustand.
    await expect(deviceCard.locator(".text-warning")).toHaveCount(0);
  });

  test("ohne_lagerbestand_bleibt_die_zweite_zeile_weg", async ({ page }) => {
    // Eine Zeile "0 im Lager" waere Platz ohne Inhalt.
    await mockKpi(page, { devices_online: 101, devices_assigned: 101, devices_pool: 0 });
    await page.goto("/");
    const deviceCard = page.getByTestId("kpi-card").filter({ hasText: "Geräte online" });

    await expect(deviceCard).toContainText("von 101");
    await expect(deviceCard).not.toContainText("im Lager");
  });
});
