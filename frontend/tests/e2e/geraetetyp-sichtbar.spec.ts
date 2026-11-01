import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Der Gerätetyp ist sichtbar — in der Liste und auf der Geräteseite
 * (Entscheidung Betreiber, 31.10.2026).
 *
 * **Warum das eine Prüfung braucht.** Bis zur Nachlieferung bestand das
 * Haus aus 104 Thermostaten; der Typ war keine Frage, weil es nur eine
 * Antwort gab. Mit den Relais 108 und 109 stehen zwei Geräte in derselben
 * Liste, die nichts messen und ein Ventil nicht kennen — und sie sahen
 * dort aus wie jedes andere. Auf der Geräteseite stand der Typ als
 * Enum-Wert („relay"), technisch vorhanden und kein Wort, das jemand
 * liest.
 *
 * **Jedes Gerät nennt seinen Typ, auch das Thermostat.** Nur das Relais
 * zu kennzeichnen hätte die Frage beantwortet, solange jemand die Regel
 * kennt („ohne Marke ist es ein Thermostat") — eine Information, die aus
 * dem **Fehlen** einer Marke gelesen werden muss, ist die Falle aus
 * §5.57. Deshalb prüft diese Datei beide Richtungen.
 *
 * Backend gemockt via `page.route` (§5.54: RegExp mit `(\?.*)?$`).
 */

const ADMIN = {
  id: 1,
  email: "admin@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-31T07:00:00Z",
  last_login_at: "2026-10-31T07:00:00Z",
};

/** Ein Thermostat aus dem Pool — die Nachlieferung, Etikett 105. */
const THERMOSTAT = {
  id: 105,
  dev_eui: "70b3d52dd30329c6",
  app_eui: "70b3d52dd3000000",
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "Vicki",
  label: "105",
  heating_zone_id: null,
  heating_zone: null,
  hardware_number: "V6TF410485L19W",
  measure_only: false,
  child_lock_state: "ausstehend" as const,
  rad_gesperrt_gewollt: false,
  last_seen_at: null,
  firmware_version: null,
  health_state: "healthy" as const,
  valve_state: "unbekannt" as const,
  valve_delta_k: null,
  valve_referenz: null,
  valve_referenz_median_c: null,
  valve_referenz_delta_k: null,
  battery_state: "unbekannt" as const,
  battery_voltage_median: null,
  battery_jump_at: null,
  battery_last_voltage: null,
  battery_last_at: null,
  retired_at: null,
  commissioned_at: null,
  grenzen_soll_min_c: null,
  grenzen_soll_max_c: null,
  grenzen_gemeldet_min_c: null,
  grenzen_gemeldet_max_c: null,
  grenzen_bestaetigt_um: null,
  created_at: "2026-10-31T08:00:00Z",
  updated_at: "2026-10-31T08:00:00Z",
  active_override: null,
  latest_reading: null,
};

/** Relais A, Etikett 108. */
const RELAIS = {
  ...THERMOSTAT,
  id: 108,
  dev_eui: "70b3d52ddd001f23",
  kind: "relay" as const,
  model: "MC-LW-16ASPM-01",
  label: "108",
  hardware_number: "FCN1865403KA7L",
};

async function mockListe(page: Page, geraete: unknown[]): Promise<void> {
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ADMIN) }),
  );
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(geraete) }),
  );
}

async function mockSeite(page: Page, geraet: Record<string, unknown>): Promise<void> {
  const id = geraet.id as number;
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ADMIN) }),
  );
  await page.route(new RegExp(`.*/api/v1/devices/${id}/sensor-readings(\\?.*)?$`), (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(new RegExp(`.*/api/v1/devices/${id}/audit(\\?.*)?$`), (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(new RegExp(`.*/api/v1/devices/${id}(\\?.*)?$`), (r: Route) => {
    if (r.request().method() !== "GET") return r.fallback();
    return r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(geraet),
    });
  });
}

test.describe("Gerätetyp sichtbar", () => {
  test("die Liste nennt den Typ je Zeile — Thermostat und Relais", async ({ page }) => {
    await mockListe(page, [THERMOSTAT, RELAIS]);
    await page.goto("/devices");

    const zeile105 = page.getByRole("row").filter({ hasText: "105" });
    const zeile108 = page.getByRole("row").filter({ hasText: "108" });

    await expect(zeile105.getByTestId("geraetetyp")).toHaveText(/Thermostat/);
    await expect(zeile108.getByTestId("geraetetyp")).toHaveText(/Relais/);
    // Das Attribut macht die Zuordnung prüfbar, ohne am Wort zu hängen —
    // das Wort ist Oberfläche, der Enum-Wert ist die Aussage.
    await expect(zeile108.getByTestId("geraetetyp")).toHaveAttribute("data-kind", "relay");
  });

  test("ein Relais trägt nicht die Fühler-Marke", async ({ page }) => {
    // Die Gegenprobe gegen eine naheliegende Verwechslung: „Fühler" ist
    // eine **Rolle** (ein Thermostat, das nur misst), „Relais" ist die
    // **Art** der Hardware. Ein Relais misst nie und kann die Rolle nicht
    // tragen; stünde die Marke dort, wäre die Liste doppelt falsch.
    await mockListe(page, [RELAIS]);
    await page.goto("/devices");

    await expect(page.getByTestId("geraetetyp")).toHaveText(/Relais/);
    await expect(page.getByTestId("fuehler-badge")).toHaveCount(0);
  });

  test("die Geräteseite nennt den Typ als Wort, nicht als Enum-Wert", async ({ page }) => {
    await mockSeite(page, RELAIS);
    await page.goto("/devices/108");

    const typ = page.getByTestId("geraetetyp");
    await expect(typ).toHaveText(/Relais/);
    // Und der rohe Enum-Wert steht nicht mehr da. Ohne diese Zeile wäre
    // die Änderung auch grün, wenn „relay" daneben stehen bliebe.
    await expect(page.getByText("relay", { exact: true })).toHaveCount(0);
    // Hersteller und Modell bleiben — sie standen in derselben Zeile und
    // sind nicht der Typ.
    await expect(page.getByText(/MC-LW-16ASPM-01/).first()).toBeVisible();
  });

  test("auch ein Thermostat nennt seinen Typ auf der Geräteseite", async ({ page }) => {
    await mockSeite(page, THERMOSTAT);
    await page.goto("/devices/105");

    await expect(page.getByTestId("geraetetyp")).toHaveText(/Thermostat/);
  });
});
