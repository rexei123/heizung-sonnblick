import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Paketverlust auf der Geräteseite (02.11.2026).
 *
 * Geprüft wird die Unterscheidung, die die ganze Kachel trägt: **„—" ist
 * nicht 0 %.** Unter zwei Frames im Fenster gibt es keine Lücke, die man
 * sehen könnte; eine Null wäre eine Behauptung über einen Funk, der nicht
 * gemessen wurde.
 *
 * Dazu der Fall vom Relais 109 mit seinen gemessenen 40 % und der
 * Hinweis, dass eine Rücksetzung des Zählers kein Verlust ist.
 */

const MOCK_ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-11-02T08:00:00Z",
  last_login_at: "2026-11-02T08:00:00Z",
};

const GERAET = {
  id: 9,
  dev_eui: "70b3d52ddd001e69",
  app_eui: null,
  kind: "relay",
  vendor: "mclimate",
  model: "16ASPM",
  label: "109 Eingang",
  measure_only: false,
  child_lock_state: "ausstehend",
  rad_gesperrt_gewollt: false,
  heating_zone_id: null,
  heating_zone: null,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  firmware_version: "1.5",
  last_seen_at: "2026-11-02T08:00:00Z",
  created_at: "2026-11-01T07:00:00Z",
  updated_at: "2026-11-02T08:00:00Z",
  health_state: "healthy",
  battery_state: "unbekannt",
  battery_voltage_median: null,
  battery_jump_at: null,
  battery_last_voltage: null,
  battery_last_at: null,
  valve_state: "ok",
  valve_delta_k: null,
  valve_referenz: null,
  valve_referenz_median_c: null,
  valve_referenz_delta_k: null,
  active_override: null,
  latest_reading: null,
  grenzen_soll_min_c: null,
  grenzen_soll_max_c: null,
  grenzen_ist_min_c: null,
  grenzen_ist_max_c: null,
  grenzen_bestaetigt_um: null,
};

type Verlust = {
  empfangen: number;
  erwartet: number;
  verloren: number;
  anteil_prozent: number | null;
  neustarts: number;
  doppelt: number;
  ohne_zaehler: number;
  stunden: number;
  von: string | null;
  bis: string | null;
};

async function mockSeite(page: Page, verlust: Verlust) {
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_ADMIN),
    }),
  );
  await page.route(/.*\/api\/v1\/devices\/9(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GERAET),
    }),
  );
  // Regex statt Glob: der Aufruf trägt `?stunden=24`, und `**` matcht
  // nicht zuverlässig über das `?` hinweg (§5.54).
  await page.route(/.*\/api\/v1\/devices\/9\/paketverlust(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(verlust),
    }),
  );
}

const LEER: Verlust = {
  empfangen: 1,
  erwartet: 1,
  verloren: 0,
  anteil_prozent: null,
  neustarts: 0,
  doppelt: 0,
  ohne_zaehler: 0,
  stunden: 24,
  von: "2026-11-02T06:05:00Z",
  bis: "2026-11-02T06:05:00Z",
};

test.describe("Paketverlust auf der Geräteseite", () => {
  test("der Fall vom Relais 109: 40 % stehen in Rot", async ({ page }) => {
    await mockSeite(page, {
      empfangen: 6,
      erwartet: 10,
      verloren: 4,
      anteil_prozent: 40,
      neustarts: 0,
      doppelt: 0,
      ohne_zaehler: 0,
      stunden: 24,
      von: "2026-11-02T06:05:00Z",
      bis: "2026-11-02T08:00:00Z",
    });
    await page.goto("/devices/9");

    const anteil = page.getByTestId("paketverlust-anteil");
    await expect(anteil).toHaveText("40.0 %");
    await expect(anteil).toHaveClass(/text-error/);
    await expect(page.getByTestId("paketverlust-hinweis")).toContainText(
      "4 von 10 Frames fehlen",
    );
  });

  test("zu wenige Frames: ein Strich, und der Text sagt warum", async ({ page }) => {
    await mockSeite(page, LEER);
    await page.goto("/devices/9");

    await expect(page.getByTestId("paketverlust-anteil")).toHaveText("—");
    // **Der Kern der Kachel.** Ein Strich, der für 0 % gelesen wird,
    // wäre schlimmer als keine Kachel.
    await expect(page.getByTestId("paketverlust-hinweis")).toContainText(
      "Das ist nicht 0 %",
    );
  });

  test("eine Rücksetzung des Zählers wird als Neustart ausgewiesen", async ({ page }) => {
    await mockSeite(page, {
      empfangen: 12,
      erwartet: 12,
      verloren: 0,
      anteil_prozent: 0,
      neustarts: 1,
      doppelt: 0,
      ohne_zaehler: 0,
      stunden: 24,
      von: "2026-11-02T06:05:00Z",
      bis: "2026-11-02T08:00:00Z",
    });
    await page.goto("/devices/9");

    await expect(page.getByTestId("paketverlust-anteil")).toHaveText("0.0 %");
    await expect(page.getByTestId("paketverlust-neustarts")).toContainText(
      "Ein Neustart",
    );
    await expect(page.getByTestId("paketverlust-neustarts")).toContainText(
      "nicht als Verlust gerechnet",
    );
  });
});
