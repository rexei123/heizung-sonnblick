import { test, expect, type ConsoleMessage, type Page, type Route } from "./fixtures";

/**
 * Sprint 21 A1 — Playwright-E2E fuer den Verlauf-Reiter.
 *
 * Backend via ``page.route()`` gemockt; §5.54: RegExp-Routes mit
 * ``(\?.*)?$``, weil ``/history?range=24h`` und
 * ``/occupancies?room_id=...`` Query-Strings tragen.
 *
 * Gepruefte Zusagen:
 *  1. Der Reiter zeichnet je Zone eine Linie, mit Sollwert-Linie daneben,
 *     und beschriftet die hinterlegten Flaechen sichtbar.
 *  2. Der Umschalter holt den anderen Bereich — mit ``range=7d`` im
 *     Request, nicht nur in der Anzeige.
 *  3. **Die recharts-Warnung ``width(-1) and height(-1)`` erscheint
 *     nicht.** Das ist AK 3 des Briefs, und es ist der Grund, warum dieser
 *     Test die Konsole mitliest: eine Warnung, die niemand pruefen kann,
 *     kommt zurueck.
 *  4. Ohne Messwerte steht ein Satz, kein leeres Diagramm.
 */

const MOCK_ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  last_login_at: "2026-10-14T06:00:00Z",
};

const ROOM = {
  id: 101,
  number: "101",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "occupied",
  guest_override_blocked: false,
  notes: null,
  has_active_override: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-14T06:00:00Z",
};

const ZONE_SCHLAF = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  health_state: "ok" as const,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

const ZONE_BAD = { ...ZONE_SCHLAF, id: 202, kind: "bathroom" as const, name: "Bad" };

/** Festes Fenster, damit die Erwartungen nicht mit dem Kalender wandern. */
const BIS = Date.parse("2026-10-08T10:00:00Z");

function verlauf(range: "24h" | "7d"): Record<string, unknown> {
  const eimer = range === "24h" ? 10 : 60;
  const fenster = range === "24h" ? 24 * 3600_000 : 7 * 24 * 3600_000;
  const von = BIS - fenster;
  const punkte = (zoneVersatz: number) =>
    Array.from({ length: 12 }, (_, i) => ({
      t: new Date(von + i * eimer * 60_000).toISOString(),
      temperature: 20 + zoneVersatz + (i % 3) * 0.5,
      setpoint: i < 6 ? 21 : 18,
    }));
  return {
    room_id: 101,
    range,
    bucket_minutes: eimer,
    range_from: new Date(von).toISOString(),
    range_to: new Date(BIS).toISOString(),
    timezone: "Europe/Vienna",
    night_window: { start: "22:00:00", end: "06:00:00" },
    night_bands: [
      {
        start: new Date(von + 3600_000).toISOString(),
        end: new Date(von + 5 * 3600_000).toISOString(),
      },
    ],
    zones: [
      { zone_id: ZONE_SCHLAF.id, name: "Schlafzimmer", kind: "bedroom", points: punkte(0) },
      { zone_id: ZONE_BAD.id, name: "Bad", kind: "bathroom", points: punkte(1) },
    ],
  };
}

function leererVerlauf(): Record<string, unknown> {
  return {
    ...verlauf("24h"),
    night_bands: [],
    zones: [{ zone_id: ZONE_SCHLAF.id, name: "Schlafzimmer", kind: "bedroom", points: [] }],
  };
}

async function mockApi(
  page: Page,
  opts: { leer?: boolean } = {},
): Promise<{ bereiche: string[] }> {
  const bereiche: string[] = [];

  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_ADMIN),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ROOM),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([ZONE_SCHLAF, ZONE_BAD]),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/history(\?.*)?$/, async (route: Route) => {
    const url = new URL(route.request().url());
    const range = url.searchParams.get("range") ?? "24h";
    bereiche.push(range);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        opts.leer ? leererVerlauf() : verlauf(range === "7d" ? "7d" : "24h"),
      ),
    });
  });

  await page.route(/.*\/api\/v1\/occupancies(\?.*)?$/, async (route: Route) => {
    const von = BIS - 24 * 3600_000;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: 1,
            room_id: 101,
            check_in: new Date(von + 6 * 3600_000).toISOString(),
            check_out: new Date(von + 18 * 3600_000).toISOString(),
            guest_count: 2,
            source: "manual",
            external_id: null,
            is_active: true,
            cancelled_at: null,
            created_at: "2026-10-01T10:00:00Z",
            updated_at: "2026-10-01T10:00:00Z",
          },
        ],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    });
  });

  return { bereiche };
}

/** Sammelt Konsolen-Warnungen, die auf die recharts-Groessenmeldung passen. */
function groessenWarnungen(page: Page): string[] {
  const treffer: string[] = [];
  page.on("console", (msg: ConsoleMessage) => {
    const text = msg.text();
    if (/width\(-?\d+\) and height\(-?\d+\)/.test(text) || text.includes("should be greater")) {
      treffer.push(text);
    }
  });
  return treffer;
}

test.describe("Sprint 21 A1 — Zimmer-Verlauf", () => {
  test("verlauf_reiter_zeichnet_zonen_und_beschriftet_die_flaechen", async ({ page }) => {
    const warnungen = groessenWarnungen(page);
    await mockApi(page);
    await page.goto("/zimmer/101");

    await page.getByRole("button", { name: "Verlauf", exact: true }).click();

    await expect(page.getByTestId("room-history-chart")).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Verlauf" })).toBeVisible();

    // Je Zone zwei Reihen in der Legende: Ist und Soll.
    for (const name of ["Schlafzimmer", "Schlafzimmer (Soll)", "Bad", "Bad (Soll)"]) {
      await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
    }

    // Die hinterlegten Flaechen sind beschriftet und nicht nur gefaerbt.
    await expect(page.getByText("Belegt", { exact: true })).toBeVisible();
    await expect(page.getByText("Nachtabsenkung", { exact: true })).toBeVisible();

    // Takt und Absenkungs-Fenster stehen als Text da.
    await expect(page.getByText(/Alle 10 Minuten zusammengefasst/)).toBeVisible();
    await expect(page.getByText(/Absenkung 22:00–06:00 Ortszeit/)).toBeVisible();

    expect(warnungen, "recharts-Groessenwarnung in der Konsole").toEqual([]);
  });

  test("umschalter_holt_sieben_tage_vom_server", async ({ page }) => {
    const warnungen = groessenWarnungen(page);
    const { bereiche } = await mockApi(page);
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Verlauf", exact: true }).click();
    await expect(page.getByTestId("room-history-chart")).toBeVisible();

    await page.getByRole("button", { name: "7 Tage" }).click();

    // Der Bereich muss im Request stehen, nicht nur im Knopf — sonst zeigt
    // die Oberflaeche 24 Stunden und behauptet sieben Tage.
    await expect.poll(() => bereiche).toContain("7d");
    await expect(page.getByText(/Alle 1 Stunde zusammengefasst/)).toBeVisible();
    await expect(page.getByRole("button", { name: "7 Tage" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    expect(warnungen).toEqual([]);
  });

  test("ohne_messwerte_steht_ein_satz_statt_eines_leeren_diagramms", async ({ page }) => {
    await mockApi(page, { leer: true });
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Verlauf", exact: true }).click();

    await expect(
      page.getByText("Für diesen Zeitraum liegen keine Messwerte vor."),
    ).toBeVisible();
    await expect(page.getByTestId("room-history-chart")).toHaveCount(0);
  });

  test("auch_das_geraete_diagramm_warnt_nicht_mehr", async ({ page }) => {
    // Das bestehende Diagramm (Sprint 7) teilt seit A1 dieselbe Huelle.
    // Der Hotelier hat die Warnung dort gesehen, also wird sie dort
    // geprueft — nicht nur am neuen Diagramm.
    const warnungen = groessenWarnungen(page);
    await page.route("**/api/v1/**", async (route: Route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_ADMIN),
      });
    });
    await page.route(/.*\/api\/v1\/devices\/42(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 42,
          dev_eui: "aabbccddeeff0011",
          app_eui: null,
          kind: "thermostat",
          vendor: "mclimate",
          model: "Vicki",
          label: "Vicki 101",
          heating_zone_id: 201,
          retired_at: null,
          retired_reason: null,
          replaced_by_device_id: null,
          last_seen_at: new Date(BIS).toISOString(),
          created_at: "2026-05-01T10:00:00Z",
          updated_at: "2026-10-14T06:00:00Z",
          valve_state: "ok",
          valve_delta_k: null,
        }),
      });
    });
    await page.route(/.*\/api\/v1\/devices\/42\/sensor-readings(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          Array.from({ length: 6 }, (_, i) => ({
            time: new Date(BIS - i * 600_000).toISOString(),
            device_id: 42,
            temperature: 21 + i * 0.1,
            setpoint: 21,
            valve_position: 0,
            battery_voltage: 3.1,
            battery_percent: 80,
            rssi: -90,
            snr: 7,
            fcnt: 100 + i,
          })),
        ),
      });
    });

    await page.goto("/devices/42");
    await expect(page.getByTestId("sensor-readings-chart")).toBeVisible();
    expect(warnungen, "recharts-Groessenwarnung auf der Geraeteseite").toEqual([]);
  });
});
