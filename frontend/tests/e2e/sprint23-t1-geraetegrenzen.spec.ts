import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 23 T1 — Grenzen am Gerät (T1.5) und die Historie (T1.7).
 *
 * Geprüft wird, was der Betreiber am 21./22.10.2026 in Zimmer 306
 * gesehen hat und was daran falsch war:
 *
 * 1. **„30 °C, aktiv"** bei wirksamen 25. Der Gastwunsch steht am
 *    Override, gekappt wird in Layer 5 — die Anzeige las nur den
 *    ungekappten Wert und behauptete eine Wirkung, die es nicht gibt.
 * 2. **„manuell aufgehoben"** für `superseded` und
 *    `room_override_blocked`. Beide sind automatische Vorgänge; die
 *    Zuordnung prüfte auf das Wortanfang-Muster `auto` und verfehlte
 *    beide. In einer Historie mit zwölf Drehungen stand das elfmal.
 * 3. Dazu neu: **„Grenzen am Gerät"**, und zwar aus der Antwort des
 *    Geräts — nicht aus dem, was wir gesendet haben.
 */

const MOCK_ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-26T08:00:00Z",
  last_login_at: "2026-10-26T08:00:00Z",
};

function geraet(opts: {
  sollMin?: number | null;
  sollMax?: number | null;
  istMin?: number | null;
  istMax?: number | null;
  bestaetigtUm?: string | null;
}): Record<string, unknown> {
  return {
    id: 7,
    dev_eui: "70b3d52dd3034de4",
    app_eui: null,
    kind: "thermostat",
    vendor: "mclimate",
    model: "vicki",
    label: "107 Schlafzimmer",
    measure_only: false,
    child_lock_state: "ausstehend",
    heating_zone_id: 201,
    heating_zone: null,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    firmware_version: "4.5",
    last_seen_at: "2026-10-26T08:00:00Z",
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-26T08:00:00Z",
    health_state: "healthy",
    battery_state: "ok",
    battery_voltage_median: 3.1,
    battery_jump_at: null,
    battery_last_voltage: 3.1,
    battery_last_at: "2026-10-26T08:00:00Z",
    valve_state: "ok",
    valve_delta_k: null,
    valve_referenz: null,
    valve_referenz_median_c: null,
    valve_referenz_delta_k: null,
    active_override: null,
    latest_reading: null,
    grenzen_soll_min_c: opts.sollMin === undefined ? 15 : opts.sollMin,
    grenzen_soll_max_c: opts.sollMax === undefined ? 25 : opts.sollMax,
    grenzen_ist_min_c: opts.istMin ?? null,
    grenzen_ist_max_c: opts.istMax ?? null,
    grenzen_bestaetigt_um: opts.bestaetigtUm ?? null,
  };
}

async function mockGeraet(page: Page, opts: Parameters<typeof geraet>[0]) {
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
  await page.route(/.*\/api\/v1\/devices\/7(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(geraet(opts)),
    }),
  );
}

test.describe("Sprint 23 T1 Grenzen am Gerät", () => {
  test("ohne Antwort steht „nicht bestätigt“ und kein Fehler", async ({ page }) => {
    await mockGeraet(page, {});
    await page.goto("/devices/7");

    const karte = page.getByTestId("geraetegrenzen-karte");
    await expect(karte).toBeVisible();
    await expect(page.getByTestId("geraetegrenzen-ist")).toHaveText("nicht bestätigt");
    // Der Satz, der verhindert, dass jemand daraus einen Fehler liest.
    await expect(karte).toContainText("kein Fehler");
    // Das Soll steht trotzdem da — sonst wüsste niemand, worauf gewartet wird.
    await expect(karte).toContainText("Soll 15–25 °C");
  });

  test("stimmt die Antwort, steht sie mit Zeitpunkt da", async ({ page }) => {
    await mockGeraet(page, {
      istMin: 15,
      istMax: 25,
      bestaetigtUm: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
    });
    await page.goto("/devices/7");

    await expect(page.getByTestId("geraetegrenzen-ist")).toHaveText("15–25 °C");
    await expect(page.getByTestId("geraetegrenzen-karte")).toContainText("bestätigt");
    await expect(page.getByTestId("geraetegrenzen-abweichung")).toHaveCount(0);
  });

  test("weicht die Antwort ab, steht beides da", async ({ page }) => {
    // Werkseinstellung am Gerät, obwohl 15/25 gelten soll: genau der
    // Zustand, in dem der Gast auf 30 drehen kann.
    await mockGeraet(page, {
      istMin: 5,
      istMax: 30,
      bestaetigtUm: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    });
    await page.goto("/devices/7");

    await expect(page.getByTestId("geraetegrenzen-ist")).toHaveText("5–30 °C");
    await expect(page.getByTestId("geraetegrenzen-abweichung")).toContainText(
      "Soll wäre 15–25 °C",
    );
  });

  test("ohne Zone gibt es kein Soll, und die Karte sagt es", async ({ page }) => {
    await mockGeraet(page, { sollMin: null, sollMax: null });
    await page.goto("/devices/7");

    await expect(page.getByTestId("geraetegrenzen-karte")).toContainText(
      "keiner Zone zugeordnet",
    );
  });

  test("die Karte nennt, dass die Grenze nur für das Rad gilt", async ({ page }) => {
    // Das ist die Aussage, die verhindert, dass jemand die Grenze für
    // einen Eingriff in die Steuerung hält — Frostschutz und
    // Fenster-Sicherheit bleiben wirksam.
    await mockGeraet(page, { istMin: 15, istMax: 25 });
    await page.goto("/devices/7");

    await expect(page.getByTestId("geraetegrenzen-karte")).toContainText("nur für das Drehrad");
  });
});
