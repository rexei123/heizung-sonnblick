import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 22 T4+T5 — die übrigen acht Stellen aus der Durchsicht.
 *
 * T4 (Konfiguration, **lesbar** mit gesperrtem Speichern): Raumtypen,
 * Temperaturen & Zeiten, Hotel, API & Webhooks.
 * T5 (Stammdaten und Geräte): „Neues Zimmer", Geräte-Bezeichnung,
 * „Gerät hinzufügen", Pairing-Seite.
 *
 * **Jeder Test fährt beide Rollen** — ein Test, der nur „Mitarbeiter sieht
 * nichts" prüft, wäre auch grün, wenn der Knopf für niemanden mehr
 * erscheint.
 *
 * Alle betroffenen Endpunkte sind serverseitig `require_admin`; diese
 * Datei prüft die Oberfläche (§5.30).
 */

const NOW = "2026-10-14T06:00:00Z";
type Rolle = "admin" | "mitarbeiter";

function user(rolle: Rolle) {
  return {
    id: rolle === "admin" ? 1 : 2,
    email: `${rolle}@hotel.example.com`,
    role: rolle,
    is_active: true,
    must_change_password: false,
    created_at: NOW,
    updated_at: NOW,
    last_login_at: NOW,
  };
}

const RAUMTYP = {
  id: 1,
  name: "Doppelzimmer",
  description: "Standard",
  default_t_occupied: "21.0",
  default_t_vacant: "18.0",
  default_t_night: "19.0",
  created_at: NOW,
  updated_at: NOW,
};

const ZIMMER = {
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
  created_at: NOW,
  updated_at: NOW,
};

const GERAET = {
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
  last_seen_at: NOW,
  created_at: NOW,
  updated_at: NOW,
  valve_state: "ok",
  valve_delta_k: null,
  battery_voltage_median: 3.1,
  mounted_confirmed_at: NOW,
};

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
  occupancy_import_expected_by_local: "11:00:00",
  created_at: NOW,
  updated_at: NOW,
  last_mail_attempt_at: null,
  last_mail_error: null,
};

const RULE_CONFIG_GLOBAL = {
  id: 1,
  t_occupied: "21.0",
  t_vacant: "18.0",
  t_night: "19.0",
  night_start: "22:00:00",
  night_end: "06:00:00",
  preheat_minutes_before_checkin: 60,
  created_at: NOW,
  updated_at: NOW,
};

const IMPORT_LOG = {
  status: "green",
  last_success_at: NOW,
  // Zod verlangt **alle** Felder; fehlt eines, wirft `parse` und die Seite
  // zeigt „Import-Status nicht verfügbar" (§5.64). Die erste Fassung dieses
  // Mocks hatte `expected_by_local`, `today_received` und `imports` nicht —
  // der Screenshot des roten Laufs hat es gezeigt.
  expected_by_local: "11:00:00",
  expected_by_local_label: "11:00 MESZ",
  today_received: true,
  imports: [],
};

/** Ein Mock für alle Seiten dieser Datei; `schreibzugriffe` fängt Ausrutscher. */
async function mockApi(page: Page, rolle: Rolle): Promise<{ schreibzugriffe: string[] }> {
  const schreibzugriffe: string[] = [];

  const json = (route: Route, body: unknown) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  await page.route("**/api/v1/**", (route: Route) => {
    if (route.request().method() !== "GET") {
      schreibzugriffe.push(
        `${route.request().method()} ${new URL(route.request().url()).pathname}`,
      );
    }
    return json(route, []);
  });
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r) => json(r, user(rolle)));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r) => json(r, [RAUMTYP]));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r) => json(r, [ZIMMER]));
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (r) => json(r, [GERAET]));
  await page.route(/.*\/api\/v1\/global-config(\?.*)?$/, (r) => json(r, GLOBAL_CONFIG));
  await page.route(/.*\/api\/v1\/rule-configs\/global(\?.*)?$/, (r) =>
    json(r, RULE_CONFIG_GLOBAL),
  );
  await page.route(/.*\/api\/v1\/scenarios(\?.*)?$/, (r) => json(r, []));
  await page.route(/.*\/api\/v1\/integrations\/occupancy-import\/log(\?.*)?$/, (r) =>
    json(r, IMPORT_LOG),
  );

  return { schreibzugriffe };
}

const HINWEIS = /Änderungen sind Administratoren vorbehalten/;

/**
 * Wartet, bis die Rolle in der Seitenleiste steht.
 *
 * Ohne diesen Anker prüft ein Test gegen den Zustand **vor** der
 * `/auth/me`-Antwort: `user` ist dann `null`, und `null` darf nichts. Ein
 * „Mitarbeiter sieht keinen Knopf" wäre damit auch grün, wenn die Seite
 * nur noch nicht fertig geladen hat.
 */
async function rolleGeladen(page: Page, rolle: Rolle) {
  await expect(
    page.getByText(rolle === "admin" ? "Administrator" : "Mitarbeiter", { exact: true }),
  ).toBeVisible();
}

test.describe("Sprint 22 T4 — Konfiguration lesbar, Speichern gesperrt", () => {
  test("raumtypen_mitarbeiter_liest_und_aendert_nicht", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await page.goto("/raumtypen");

    // Lesen: der Typ steht in der Liste.
    await expect(page.getByText("Doppelzimmer").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Neuer Raumtyp" })).toHaveCount(0);

    // Bearbeiten öffnen: Werte lesbar, Speichern gesperrt, Löschen weg.
    await page.getByText("Doppelzimmer").first().click();
    await expect(page.getByRole("button", { name: "Löschen" })).toHaveCount(0);
    await expect(page.getByText(HINWEIS).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Aktualisieren" })).toBeDisabled();

    expect(schreibzugriffe).toEqual([]);
  });

  test("raumtypen_admin_darf_alles", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/raumtypen");

    await expect(page.getByRole("button", { name: "Neuer Raumtyp" })).toBeVisible();
    await page.getByText("Doppelzimmer").first().click();
    await expect(page.getByRole("button", { name: "Löschen" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Aktualisieren" })).toBeEnabled();
    await expect(page.getByText(HINWEIS)).toHaveCount(0);
  });

  test("temperaturen_mitarbeiter_sieht_werte_ohne_stift", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await page.goto("/einstellungen/temperaturen-zeiten");
    await rolleGeladen(page, "mitarbeiter");

    // Der Vorgabe-Reiter ist „Globale Zeiten" — dort steht das
    // Nachtfenster. (Erste Fassung dieses Tests suchte „21.0" und damit im
    // falschen Reiter; der Lauf hat es gemeldet.)
    await expect(page.getByRole("tab", { name: "Globale Zeiten" })).toBeVisible();
    await expect(page.getByText("22:00").first()).toBeVisible();
    // Aber keine Zelle ist anklickbar.
    await expect(page.getByRole("button", { name: /bearbeiten$/ })).toHaveCount(0);

    expect(schreibzugriffe).toEqual([]);
  });

  test("temperaturen_admin_kann_bearbeiten", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/einstellungen/temperaturen-zeiten");
    await rolleGeladen(page, "admin");

    // `expect(await …count()).toBeGreaterThan(0)` wäre eine **einmalige**
    // Messung ohne Wiederholung — sie fiel, solange die Rolle noch nicht da
    // war. Ein Locator-Matcher wartet.
    await expect(page.getByRole("button", { name: /bearbeiten$/ }).first()).toBeVisible();
  });

  test("hotel_und_api_mitarbeiter_speichert_nicht", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");

    await page.goto("/einstellungen/hotel");
    // Erst die Seite, dann das Steuerelement: die Seite rendert ihr
    // Formular erst nach der Konfigurations-Abfrage.
    await expect(page.getByRole("heading", { name: "Hotel-Stammdaten" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Speichern" })).toBeDisabled();
    await expect(page.getByText(HINWEIS).first()).toBeVisible();

    // „API & Webhooks" bleibt sichtbar und lesbar (Entscheidung 14.10.):
    // der Import-Status ist eine Mitarbeiter-Frage.
    await page.goto("/einstellungen/api");
    await expect(page.getByRole("heading", { name: /API & Webhooks/ })).toBeVisible();
    await expect(page.getByText("Aktuell")).toBeVisible();
    await expect(page.getByRole("button", { name: "Speichern" })).toBeDisabled();
    await expect(page.getByText(HINWEIS).first()).toBeVisible();

    expect(schreibzugriffe).toEqual([]);
  });

  test("hotel_und_api_admin_speichert", async ({ page }) => {
    await mockApi(page, "admin");

    await page.goto("/einstellungen/hotel");
    await expect(page.getByRole("heading", { name: "Hotel-Stammdaten" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Speichern" })).toBeEnabled();

    await page.goto("/einstellungen/api");
    await expect(page.getByRole("heading", { name: /API & Webhooks/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Speichern" })).toBeEnabled();
  });
});

test.describe("Sprint 22 T5 — Stammdaten und Geräte", () => {
  test("mitarbeiter_sieht_kein_neues_zimmer", async ({ page }) => {
    await mockApi(page, "mitarbeiter");
    await page.goto("/zimmer");

    await expect(page.getByText("101").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Neues Zimmer" })).toHaveCount(0);
  });

  test("admin_sieht_neues_zimmer", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/zimmer");

    await expect(page.getByRole("button", { name: "Neues Zimmer" })).toBeVisible();
  });

  test("mitarbeiter_sieht_geraete_ohne_stift_und_ohne_hinzufuegen", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await page.goto("/devices");

    // Die Bezeichnung bleibt lesbar und verlinkt — nur der Stift ist weg.
    await expect(page.getByRole("link", { name: "Vicki 101" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Bezeichnung bearbeiten" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Gerät hinzufügen" })).toHaveCount(0);

    expect(schreibzugriffe).toEqual([]);
  });

  test("admin_sieht_stift_und_hinzufuegen", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/devices");

    await expect(
      page.getByRole("button", { name: "Bezeichnung bearbeiten" }).first(),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Gerät hinzufügen" })).toBeVisible();
  });

  test("pairing_seite_hat_eine_schranke", async ({ page }) => {
    // Der Weg hierher ist ausgeblendet; die Schranke faengt Lesezeichen
    // und getippte Adressen ab.
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await page.goto("/devices/pair");

    await expect(
      page.getByText("Geräte anlegen und zuordnen ist Administratoren vorbehalten."),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Zur Geräteliste" })).toBeVisible();
    // Kein Schritt des Assistenten ist erreichbar.
    await expect(page.getByRole("button", { name: "Gerät anlegen" })).toHaveCount(0);

    expect(schreibzugriffe).toEqual([]);
  });

  test("pairing_seite_oeffnet_fuer_admin", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/devices/pair");

    await expect(page.getByText(/ist Administratoren vorbehalten/)).toHaveCount(0);
  });
});

/**
 * Nachtrag zu T5, gefunden beim Gate-Inventar fuer T9 (14.10.2026).
 *
 * Die Durchsicht hatte zehn Stellen; dies sind die **elfte und
 * zwoelfte**: auf `/devices/[id]` tragen die Bezeichnung und die
 * Hardware-Nummer je einen Stift, beide schreiben
 * `PATCH /devices/{id}` (`require_admin`, `api/v1/devices.py:362`),
 * und beide waren offen. Dieselbe Klasse wie die Befunde des Hoteliers:
 * nicht die Liste war das Problem, sondern die Seite daneben.
 *
 * Gefunden wurde es nur, weil das Inventar jede Seite gegen ihr Gate
 * stellen musste statt die Liste aus dem Brief abzuarbeiten — dort
 * stand „Thermostate: Bezeichnung inline", und das las sich wie die
 * Listen-Zelle allein.
 */
async function mockGeraetDetail(page: Page) {
  const json = (route: Route, body: unknown) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  await page.route(/.*\/api\/v1\/devices\/42(\?.*)?$/, (r) => {
    if (r.request().method() !== "GET") return r.fallback();
    return json(r, { ...GERAET, hardware_number: "MDC5419731K6UF" });
  });
  await page.route(/.*\/api\/v1\/devices\/42\/sensor-readings(\?.*)?$/, (r) => json(r, []));
  await page.route(/.*\/api\/v1\/devices\/.*\/hardware-status(\?.*)?$/, (r) =>
    json(r, {
      status: "active",
      last_seen: NOW,
      source: "window",
      mounted_confirmed_at: NOW,
      frames_in_window: 3,
      window_minutes: 30,
    }),
  );
}

test.describe("Sprint 22 T5 (Nachtrag) — Geraete-Detailseite", () => {
  test("detailseite_mitarbeiter_sieht_keine_stifte", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await mockGeraetDetail(page);
    await page.goto("/devices/42");
    await rolleGeladen(page, "mitarbeiter");

    // Die Werte bleiben lesbar — sie sind Betriebswissen.
    await expect(page.getByRole("heading", { level: 1, name: "Vicki 101" })).toBeVisible();
    await expect(page.getByTestId("hardware-number-row")).toContainText("MDC5419731K6UF");

    // Die Stifte sind weg, nicht grau.
    await expect(page.getByRole("button", { name: "Bezeichnung bearbeiten" })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Hardware-Nummer bearbeiten" }),
    ).toHaveCount(0);

    expect(schreibzugriffe).toEqual([]);
  });

  test("detailseite_admin_behaelt_beide_stifte", async ({ page }) => {
    await mockApi(page, "admin");
    await mockGeraetDetail(page);
    await page.goto("/devices/42");
    await rolleGeladen(page, "admin");

    await expect(page.getByRole("button", { name: "Bezeichnung bearbeiten" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Hardware-Nummer bearbeiten" }),
    ).toBeVisible();

    // Und der Stift tut, was er verspricht: das Feld oeffnet sich.
    await page.getByRole("button", { name: "Bezeichnung bearbeiten" }).click();
    await expect(page.getByRole("textbox")).toHaveValue("Vicki 101");
  });
});
