import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 21 A2 — Playwright-E2E fuer die Zimmer-Kopfzeile.
 *
 * Backend via ``page.route()`` gemockt, kein laufender FastAPI noetig
 * (Pattern aus ``sprint12c-room-override-blocked.spec.ts``). §5.54:
 * RegExp-Routes mit ``(\?.*)?$``, weil die GET-Aufrufe Query-Strings
 * tragen und Glob-Patterns darueber nicht zuverlaessig matchen.
 *
 * Geprueft werden die vier Zusagen von A2:
 *  1. Belegtes Zimmer: "Temperatur aendern" ist der Hauptknopf und fuehrt
 *     in die Uebersteuerung.
 *  2. Freies Zimmer: Knopf grau mit sichtbarem Grund, und im Panel steht
 *     der Hinweis statt des Formulars — statt einer Abweisung nach
 *     "Anwenden".
 *  3. "Zimmer loeschen" ist aus der Kopfzeile verschwunden und steht im
 *     Gefahrenbereich der Stammdaten.
 *  4. Rolle ``mitarbeiter``: kein Loeschen, keine Geraete-Handgriffe,
 *     "Temperatur aendern" aber schon.
 *
 * Was diese Tests NICHT pruefen: dass der Server die versteckten
 * Handlungen abweist. Das tut er (``require_admin``), und es gehoert in
 * die Backend-Tests — eine versteckte Schaltflaeche ist Bedienung, kein
 * Zugangsschutz (CLAUDE.md §5.30, ``lib/auth/rechte.ts``).
 */

const ZONE = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

const DEVICE_IN_ROOM = {
  id: 42,
  dev_eui: "aabbccddeeff0011",
  app_eui: null,
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "Vicki",
  label: "Vicki Schlafzimmer 101",
  heating_zone_id: ZONE.id,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: new Date().toISOString(),
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-15T10:00:00Z",
};

function userMock(role: "admin" | "mitarbeiter"): Record<string, unknown> {
  return {
    id: role === "admin" ? 1 : 2,
    email: role === "admin" ? "chef@hotel.example.com" : "rezeption@hotel.example.com",
    role,
    is_active: true,
    must_change_password: false,
    created_at: "2026-05-01T10:00:00Z",
    updated_at: "2026-05-14T10:00:00Z",
    last_login_at: "2026-10-14T06:00:00Z",
  };
}

function roomMock(status: "occupied" | "vacant"): Record<string, unknown> {
  return {
    id: 101,
    number: "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status,
    guest_override_blocked: false,
    notes: null,
    has_active_override: false,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-14T06:00:00Z",
  };
}

function engineTrace(): unknown[] {
  return [
    {
      time: new Date().toISOString(),
      room_id: 101,
      evaluation_id: "00000000-0000-0000-0000-000000000a21",
      layer: "window_safety",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: { detail: "no_open_window", open_zones: [] },
    },
  ];
}

async function mockApi(
  page: Page,
  opts: { role: "admin" | "mitarbeiter"; status: "occupied" | "vacant" },
): Promise<void> {
  // Catch-all zuerst: Playwright trifft die zuletzt registrierte Route.
  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(userMock(opts.role)),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(roomMock(opts.status)),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([ZONE]),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/engine-trace(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(engineTrace()),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([DEVICE_IN_ROOM]),
    });
  });
}

test.describe("Sprint 21 A2 — Temperatur aendern", () => {
  test("belegtes_zimmer_hauptknopf_fuehrt_in_die_uebersteuerung", async ({ page }) => {
    await mockApi(page, { role: "admin", status: "occupied" });
    await page.goto("/zimmer/101");

    // Die Kopfzeile des Zimmers, nicht die der App-Hülle: ueber das h1
    // gefiltert statt ueber die Reihenfolge.
    const header = page
      .locator("header")
      .filter({ has: page.getByRole("heading", { level: 1, name: "Zimmer 101" }) });
    const knopf = page.getByRole("button", { name: "Temperatur ändern" });
    await expect(knopf).toBeEnabled();
    await expect(page.getByText("nur bei belegtem Zimmer")).toHaveCount(0);

    // Die Kopfzeile traegt genau zwei Handlungen: der Hauptknopf und die
    // Sperre. Kein "Zimmer loeschen" mehr — das ist Punkt 3 von A2, hier
    // als Struktur-Zusicherung statt als Klassen-Vergleich.
    await expect(header.getByRole("button")).toHaveCount(2);
    await expect(
      header.getByRole("button", { name: "Übersteuerung sperren", exact: true }),
    ).toBeVisible();

    await knopf.click();
    await expect(
      page.getByRole("heading", { level: 2, name: "Übersteuerung" }),
    ).toBeVisible();
  });

  test("freies_zimmer_graut_knopf_aus_und_nennt_den_grund", async ({ page }) => {
    await mockApi(page, { role: "admin", status: "vacant" });
    await page.goto("/zimmer/101");

    await expect(page.getByRole("button", { name: "Temperatur ändern" })).toBeDisabled();
    await expect(page.getByText("nur bei belegtem Zimmer")).toBeVisible();

    // Im Panel steht der Grund, bevor jemand etwas ausfuellt. Die
    // Abweisung mit 409 bleibt im Service, sie ist nur nicht mehr der
    // erste Hinweis.
    await page.getByRole("button", { name: "Übersteuerung", exact: true }).click();
    // Zwei Stellen, bewusst getrennt geprueft: das Banner oben im Panel und
    // der Satz in der Zonen-Karte, wo sonst das Formular stuende.
    await expect(
      page.getByText("Zimmer ist nicht belegt", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(/Zimmer ist nicht belegt — eine Wunschtemperatur/),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Anwenden" })).toHaveCount(0);
  });

  test("loeschen_steht_im_gefahrenbereich_der_stammdaten", async ({ page }) => {
    await mockApi(page, { role: "admin", status: "occupied" });
    await page.goto("/zimmer/101");

    await expect(page.getByRole("heading", { name: "Gefahrenbereich" })).toBeVisible();
    const loeschen = page.getByRole("button", { name: "Zimmer löschen" });
    await expect(loeschen).toBeVisible();

    await loeschen.click();
    await expect(page.getByText("Zimmer löschen?")).toBeVisible();
  });

  test("mitarbeiter_sieht_kein_loeschen_und_keine_geraete_handgriffe", async ({ page }) => {
    await mockApi(page, { role: "mitarbeiter", status: "occupied" });
    await page.goto("/zimmer/101");

    await expect(page.getByRole("button", { name: "Temperatur ändern" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Zimmer löschen" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Gefahrenbereich" })).toHaveCount(0);
    await expect(
      page.getByText("Stammdaten ändern ist Administratoren vorbehalten."),
    ).toBeVisible();

    await page.getByRole("button", { name: "Geräte", exact: true }).click();
    await expect(page.getByText("Vicki Schlafzimmer 101")).toBeVisible();
    await expect(page.getByRole("link", { name: /Gerät zuordnen/ })).toHaveCount(0);
    for (const name of [
      "Thermostat tauschen",
      "Thermostat stilllegen",
      "Gerät von Heizzone trennen",
    ]) {
      await expect(page.getByRole("button", { name })).toHaveCount(0);
    }
  });
});
