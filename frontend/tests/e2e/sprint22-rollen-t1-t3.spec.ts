import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 22 T1-T3 — Rollen-Gating für die hotelweiten Schalter und die
 * Heizzonen.
 *
 * **Die zwei Befunde des Hoteliers vom 14.10.2026**, angemeldet als
 * `mitarbeiter`, nichts ausprobiert:
 *
 * A. Unter „Szenarien" war der Sommermodus-Schalter sichtbar und
 *    bedienbar — und der Bestätigungsdialog sagt, dass **alle Räume** auf
 *    Frostschutz gehen.
 * B. Zimmer → Heizzonen zeigte „Zone löschen" und das Anlege-Formular.
 *
 * **Serverseitig war beides zu** (`require_admin`), es waren also
 * Sackgassen und kein Stabilitätsrisiko. Genau deshalb prüft diese Datei
 * die **Oberfläche**: dass der Server abweist, ist Sache der
 * Backend-Tests (CLAUDE.md §5.30 — verstecken ist Bedienung, kein
 * Zugangsschutz).
 *
 * Jeder Test fährt **beide** Rollen. Ein Test, der nur „Mitarbeiter sieht
 * nichts" prüft, wäre auch grün, wenn der Knopf für niemanden mehr
 * erscheint.
 */

const NOW = "2026-10-14T06:00:00Z";

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
  created_at: NOW,
  updated_at: NOW,
};

const ZONE = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  health_state: "healthy" as const,
  created_at: NOW,
  updated_at: NOW,
  active_override: null,
  mean_temperature_c: 21.0,
  engine_setpoint_c: 21.0,
};

const SZENARIO_SOMMER = {
  id: 1,
  code: "summer_mode",
  name: "Sommermodus",
  description: "Alle Räume auf Frostschutz.",
  current_global_assignment_active: false,
  created_at: NOW,
  updated_at: NOW,
};

type Rolle = "admin" | "mitarbeiter";

async function mockApi(page: Page, rolle: Rolle): Promise<{ schreibzugriffe: string[] }> {
  const schreibzugriffe: string[] = [];
  const user = {
    id: rolle === "admin" ? 1 : 2,
    email: `${rolle}@hotel.example.com`,
    role: rolle,
    is_active: true,
    must_change_password: false,
    created_at: NOW,
    updated_at: NOW,
    last_login_at: NOW,
  };

  await page.route("**/api/v1/**", (route: Route) => {
    if (route.request().method() !== "GET") {
      schreibzugriffe.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(user) }),
  );
  await page.route(/.*\/api\/v1\/scenarios(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([SZENARIO_SOMMER]),
    }),
  );
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ROOM) }),
  );
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([ZONE]) }),
  );
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "Doppelzimmer", created_at: NOW, updated_at: NOW }]),
    }),
  );
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );

  return { schreibzugriffe };
}

test.describe("Sprint 22 T2 — Szenarien", () => {
  test("mitarbeiter_sieht_den_zustand_aber_keinen_schalter", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await page.goto("/szenarien");

    // Der Zustand bleibt lesbar — das ist der Unterschied zwischen
    // „ausgeblendet" und „nur lesend".
    await expect(page.getByText("Sommermodus")).toBeVisible();
    // „Inaktiv" steht zweimal auf der Karte (Kopf-Etikett und Fusszeile) —
    // beides ist Zustand, und beides darf ein Mitarbeiter sehen.
    await expect(page.getByText("Inaktiv", { exact: true }).first()).toBeVisible();

    await expect(page.getByRole("switch")).toHaveCount(0);
    await expect(page.getByText("Schalten nur als Administrator")).toBeVisible();

    // Und nichts ist unterwegs: kein versehentlicher Schreibzugriff beim
    // Rendern.
    expect(schreibzugriffe).toEqual([]);
  });

  test("admin_sieht_den_schalter", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/szenarien");

    await expect(page.getByRole("switch")).toBeVisible();
    await expect(page.getByText("Schalten nur als Administrator")).toHaveCount(0);
  });

  test("admin_bekommt_vor_dem_schalten_die_warnung", async ({ page }) => {
    // Die Bestätigung ist der Grund, warum der Befund des Hoteliers so
    // unangenehm war: sie sagt, dass das ganze Haus auf Frostschutz geht.
    await mockApi(page, "admin");
    await page.goto("/szenarien");

    await page.getByRole("switch").click();

    await expect(page.getByText("Sommermodus aktivieren?")).toBeVisible();
    await expect(page.getByText(/Alle Räume werden auf Frostschutz gefahren/)).toBeVisible();
  });
});

test.describe("Sprint 22 T3 — Heizzonen", () => {
  test("mitarbeiter_sieht_zonen_aber_kein_loeschen_und_kein_anlegen", async ({ page }) => {
    const { schreibzugriffe } = await mockApi(page, "mitarbeiter");
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    // Lesen ja: die Zone steht da, mit ihrem Namen read-only.
    await expect(page.getByTestId("zone-card-201-name-readonly")).toBeVisible();

    // Schreiben nein — beide Stellen, und die untere war der Befund:
    // `isAdmin` deckte vorher nur den Namens-Edit.
    await expect(page.getByTestId("zone-card-201-delete-button")).toHaveCount(0);
    await expect(page.getByText("Neue Heizzone")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Hinzufügen" })).toHaveCount(0);

    expect(schreibzugriffe).toEqual([]);
  });

  test("admin_sieht_loeschen_und_anlegen", async ({ page }) => {
    await mockApi(page, "admin");
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    await expect(page.getByTestId("zone-card-201-delete-button")).toBeVisible();
    await expect(page.getByText("Neue Heizzone")).toBeVisible();
    await expect(page.getByRole("button", { name: "Hinzufügen" })).toBeVisible();
  });

  test("der_handtuchtrockner_verspricht_keine_logik_mehr", async ({ page }) => {
    // Der Klammerzusatz „(eigene Regel-Logik in Sprint 9)" stand seit
    // Sprint 8 und versprach eine Logik, die es nicht gibt —
    // `is_towel_warmer` ist ein Marker ohne Engine-Konsument (§5.43).
    await mockApi(page, "admin");
    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    await expect(page.getByText("Handtuchtrockner", { exact: true })).toBeVisible();
    await expect(page.getByText(/eigene Regel-Logik in Sprint 9/)).toHaveCount(0);
  });
});
