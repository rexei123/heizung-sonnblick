import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 21 A3 — Fehler-Auswahl in der Geraeteliste, klickbare Kacheln.
 *
 * Backend via ``page.route()`` gemockt; §5.54: RegExp mit ``(\?.*)?$``.
 *
 * Gepruefte Zusagen:
 *  1. Die Auswahl filtert die Tabelle und steht in der URL (``?zeige=``).
 *  2. Die Zahl in Klammern stimmt mit der Tabelle darunter — **dieselbe
 *     Quelle**, nicht die Kachelzahl (§5.53).
 *  3. Ein Klick auf eine Kachel landet in der passenden Auswahl, und die
 *     Kachelzahl entspricht der Zeilenzahl.
 *  4. Die Sortierung ist ein Auswahlfeld und schreibt ``?sort=label``.
 *  5. Eine leere Auswahl sagt das, statt eine leere Tabelle zu zeigen.
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

interface GeraetMock {
  id: number;
  dev_eui: string;
  label: string;
  heating_zone_id: number | null;
  health_state: "healthy" | "degraded" | "silent" | "suspicious";
  battery_state: "ok" | "warn" | "kritisch" | "unbekannt";
  valve_state:
    | "ok"
    | "unbekannt"
    | "ventil_klemmt_zu"
    | "zimmer_zu_warm"
    | "ventil_schliesst_nicht";
}

function geraet(i: number, teil: Partial<GeraetMock> = {}): Record<string, unknown> {
  const basis: GeraetMock = {
    id: i,
    dev_eui: `aabbccddeeff${String(i).padStart(4, "0")}`,
    label: `Vicki ${String(i).padStart(3, "0")}`,
    heating_zone_id: 200 + i,
    health_state: "healthy",
    battery_state: "ok",
    valve_state: "ok",
    ...teil,
  };
  return {
    ...basis,
    app_eui: null,
    kind: "thermostat",
    vendor: "mclimate",
    model: "Vicki",
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: "2026-10-14T06:00:00Z",
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-10-14T06:00:00Z",
    valve_delta_k: null,
    battery_voltage_median: 3.1,
    mounted_confirmed_at: "2026-09-20T10:00:00Z",
  };
}

/**
 * Der Datenstand: zehn Geraete, jede Auswahl trifft eine bekannte Zahl.
 *
 * | Auswahl | erwartet |
 * |---|---|
 * | Alle | 10 |
 * | Nicht online | 2 (1 silent + 1 suspicious, beide zugeordnet) |
 * | Batterie niedrig | 2 |
 * | Zimmer zu warm | 1 |
 * | Ventil pruefen | 2 (klemmt zu + schliesst nicht) |
 * | Im Lager | 3 |
 *
 * Das Lager-Geraet mit ``silent`` ist der interessante Fall: es zaehlt
 * **nicht** in "Nicht online", weil es kein Zimmer versorgt (B-21-2).
 */
const GERAETE = [
  geraet(1),
  geraet(2),
  geraet(3, { health_state: "silent" }),
  geraet(4, { health_state: "suspicious" }),
  geraet(5, { battery_state: "warn" }),
  geraet(6, { battery_state: "kritisch" }),
  geraet(7, { valve_state: "zimmer_zu_warm" }),
  geraet(8, { valve_state: "ventil_klemmt_zu" }),
  geraet(9, { valve_state: "ventil_schliesst_nicht" }),
  geraet(10, { heating_zone_id: null }),
  geraet(11, { heating_zone_id: null }),
  geraet(12, { heating_zone_id: null, health_state: "silent" }),
];

const KPI = {
  rooms_occupied: 1,
  rooms_total: 30,
  avg_temperature_celsius: 21.4,
  // Zugeordnet sind 9 (1-9), online davon 7 (ohne silent und suspicious).
  devices_online: 7,
  devices_assigned: 9,
  devices_pool: 3,
  active_overrides: 0,
  zones_window_open: 0,
  last_engine_tick: new Date().toISOString(),
  battery_low_count: 2,
  valve_check_count: 2,
  room_too_warm_count: 1,
};

async function mockApi(page: Page): Promise<void> {
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
  await page.route(/.*\/api\/v1\/dashboard\/kpi(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(KPI),
    });
  });
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GERAETE),
    });
  });
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
}

/** Datenzeilen der Geraetetabelle (ohne Kopfzeile). */
function zeilen(page: Page) {
  return page.locator("table tbody tr");
}

async function waehle(page: Page, feld: "Anzeigen" | "Sortieren", eintrag: RegExp) {
  await page.getByLabel(feld).click();
  await page.getByRole("option", { name: eintrag }).click();
}

test.describe("Sprint 21 A3 — Fehler-Auswahl", () => {
  test("auswahl_filtert_und_steht_in_der_url", async ({ page }) => {
    await mockApi(page);
    await page.goto("/devices");
    await expect(zeilen(page)).toHaveCount(12);

    await waehle(page, "Anzeigen", /^Ventil prüfen/);

    await expect(zeilen(page)).toHaveCount(2);
    await expect(page).toHaveURL(/\?zeige=ventil$/);
    await expect(page.getByText("Vicki 008")).toBeVisible();
    await expect(page.getByText("Vicki 009")).toBeVisible();
  });

  test("zahl_in_klammern_stimmt_mit_der_tabelle", async ({ page }) => {
    // Die Zahl kommt aus derselben Liste wie die Tabelle. Zwei Quellen
    // wuerden driften, und zwar unbemerkt (§5.53).
    await mockApi(page);
    await page.goto("/devices");

    await page.getByLabel("Anzeigen").click();
    for (const [eintrag, erwartet] of [
      [/^Alle \(12\)$/, 12],
      [/^Nicht online \(Funkstille\) \(2\)$/, 2],
      [/^Batterie niedrig \(2\)$/, 2],
      [/^Zimmer zu warm \(1\)$/, 1],
      [/^Ventil prüfen \(2\)$/, 2],
      [/^Im Lager \(3\)$/, 3],
    ] as const) {
      await expect(page.getByRole("option", { name: eintrag })).toBeVisible();
      void erwartet;
    }
    // Stichprobe: "Nicht online" zeigt genau zwei Zeilen — das stille
    // Lager-Geraet (012) ist NICHT dabei, es versorgt kein Zimmer.
    await page.getByRole("option", { name: /^Nicht online/ }).click();
    await expect(zeilen(page)).toHaveCount(2);
    await expect(page.getByText("Vicki 012")).toHaveCount(0);
  });

  test("kachel_fuehrt_in_die_passende_auswahl", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    const kachel = page.getByTestId("kpi-card").filter({ hasText: "Ventil prüfen" });
    await expect(kachel).toContainText("2");
    await kachel.click();

    await expect(page).toHaveURL(/\/devices\?zeige=ventil$/);
    // Die Kachel sagte 2, die Liste zeigt 2. Driften die beiden, ist einer
    // von beiden falsch — und das soll auffallen.
    await expect(zeilen(page)).toHaveCount(2);
  });

  test("kachel_geraete_online_fuehrt_zu_nicht_online", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    const kachel = page.getByTestId("kpi-card").filter({ hasText: "Geräte online" });
    await expect(kachel).toContainText("von 9");
    await expect(kachel).toContainText("3 im Lager");
    await kachel.click();

    await expect(page).toHaveURL(/\/devices\?zeige=nicht-online$/);
    // 9 zugeordnet, 7 online -> genau 2 fehlen.
    await expect(zeilen(page)).toHaveCount(2);
  });

  test("sortierung_ist_eine_auswahl_und_steht_in_der_url", async ({ page }) => {
    // Vorher war das ein Knopf, der seinen Zustand anzeigte ("Sortierung:
    // Fehlerstatus") und deshalb wie eine Beschriftung aussah.
    await mockApi(page);
    await page.goto("/devices");

    await waehle(page, "Sortieren", /^Bezeichnung$/);

    await expect(page).toHaveURL(/\?sort=label$/);
    // Nach Bezeichnung sortiert steht Vicki 001 oben; nach Fehlerstatus
    // waere es ein Geraet mit Befund.
    await expect(zeilen(page).first()).toContainText("Vicki 001");

    await waehle(page, "Sortieren", /^Fehlerstatus$/);
    await expect(page).not.toHaveURL(/sort=/);
    await expect(zeilen(page).first()).not.toContainText("Vicki 001");
  });

  test("leere_auswahl_sagt_es_statt_eine_leere_tabelle_zu_zeigen", async ({ page }) => {
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
    // Nur gesunde, zugeordnete Geraete: jede Fehler-Auswahl ist leer.
    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([geraet(1), geraet(2)]),
      });
    });

    await page.goto("/devices?zeige=ventil");

    await expect(page.getByText(/Kein Gerät in dieser Auswahl/)).toBeVisible();
    await expect(zeilen(page)).toHaveCount(0);

    await page.getByRole("button", { name: "Alle Geräte zeigen" }).click();
    await expect(zeilen(page)).toHaveCount(2);
    await expect(page).not.toHaveURL(/zeige=/);
  });

  test("unbekannte_auswahl_zeigt_alle_statt_nichts", async ({ page }) => {
    // Ein Link mit Tippfehler darf nicht wie "kein Geraet betroffen"
    // aussehen.
    await mockApi(page);
    await page.goto("/devices?zeige=quatsch");

    await expect(zeilen(page)).toHaveCount(12);
    await expect(page.getByLabel("Anzeigen")).toContainText("Alle (12)");
  });
});
