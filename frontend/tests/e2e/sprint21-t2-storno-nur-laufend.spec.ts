import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 21 T2 (B-20f-3) — „Stornieren" nur bei laufenden und künftigen
 * Belegungen.
 *
 * **Der Befund.** Die Belegungs-Liste zeigte den Knopf an jeder Zeile,
 * auch wenn `check_out` lange vorbei war. Ein Storno wirkt dort nicht mehr
 * auf die Regelung — das Zimmer ist seit der Abreise `VACANT` — und ändert
 * nur die Historie. Harmlos, aber eine Handlung anzubieten, die nichts
 * tut, kostet beim nächsten Mal Vertrauen in die, die etwas tut.
 *
 * Gemockt via ``page.route()``; §5.54: RegExp mit ``(\?.*)?$``, weil die
 * Liste mit ``from``/``to``/``active``/``limit`` fragt. Der Mock antwortet
 * auf jede Anfrage mit denselben drei Zeilen — welchen Zeitraum die Seite
 * anfragt, ist für diesen Test unerheblich.
 */

const MOCK_MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-14T06:00:00Z",
  last_login_at: "2026-10-14T06:00:00Z",
};

const ZIMMER = {
  id: 1,
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

const STUNDE = 3600_000;

/**
 * Drei Zeilen, relativ zur **Uhr des Testlaufs** — nicht zu festen Daten.
 *
 * Feste Daten wären hier die falsche Wahl: die Grenze, die dieser Test
 * prüft, ist „jetzt", und ein Datum aus dem Jahr 2026 wandert mit jedem
 * Tag weiter von ihr weg. Dieselbe Lehre wie bei der A1-Abnahme, nur in
 * die andere Richtung.
 */
function belegungen(): Record<string, unknown>[] {
  const jetzt = Date.now();
  const basis = {
    room_id: 1,
    guest_count: 2,
    source: "manual",
    external_id: null,
    is_active: true,
    cancelled_at: null,
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
  };
  return [
    {
      ...basis,
      id: 1,
      // Abgereist: vor drei Tagen angekommen, gestern weg.
      check_in: new Date(jetzt - 72 * STUNDE).toISOString(),
      check_out: new Date(jetzt - 24 * STUNDE).toISOString(),
    },
    {
      ...basis,
      id: 2,
      // Läuft: gestern angekommen, morgen weg.
      check_in: new Date(jetzt - 24 * STUNDE).toISOString(),
      check_out: new Date(jetzt + 24 * STUNDE).toISOString(),
    },
    {
      ...basis,
      id: 3,
      // Künftig.
      check_in: new Date(jetzt + 48 * STUNDE).toISOString(),
      check_out: new Date(jetzt + 96 * STUNDE).toISOString(),
    },
  ];
}

async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_MITARBEITER),
    }),
  );
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([ZIMMER]),
    }),
  );
  await page.route(/.*\/api\/v1\/occupancies(\?.*)?$/, (route: Route) => {
    const zeilen = belegungen();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: zeilen,
        total: zeilen.length,
        limit: 100,
        offset: 0,
      }),
    });
  });
}

function zeilen(page: Page) {
  return page.locator("table tbody tr");
}

test.describe("Sprint 21 T2 — Storno nur bei laufenden Belegungen", () => {
  test("abgereiste_zeile_bietet_kein_storno_mehr", async ({ page }) => {
    await mockApi(page);
    await page.goto("/belegungen?range=all");

    await expect(zeilen(page)).toHaveCount(3);

    // Drei Zeilen, zwei Knöpfe: die abgereiste trägt stattdessen das Wort.
    await expect(page.getByRole("button", { name: "Stornieren" })).toHaveCount(2);
    await expect(page.getByText("abgereist")).toHaveCount(1);

    // Und zwar in der ersten Zeile — der mit dem Abreise-Datum in der
    // Vergangenheit.
    await expect(zeilen(page).nth(0)).toContainText("abgereist");
    await expect(zeilen(page).nth(0).getByRole("button", { name: "Stornieren" })).toHaveCount(
      0,
    );
  });

  test("laufende_und_kuenftige_zeile_behalten_den_knopf", async ({ page }) => {
    await mockApi(page);
    await page.goto("/belegungen?range=all");

    for (const i of [1, 2]) {
      await expect(
        zeilen(page).nth(i).getByRole("button", { name: "Stornieren" }),
      ).toBeVisible();
      await expect(zeilen(page).nth(i)).not.toContainText("abgereist");
    }
  });

  test("der_knopf_fuehrt_weiterhin_in_den_bestaetigungsdialog", async ({ page }) => {
    // T2 nimmt eine wirkungslose Handlung weg — die wirksame muss
    // unveraendert funktionieren.
    await mockApi(page);
    await page.goto("/belegungen?range=all");

    await zeilen(page).nth(1).getByRole("button", { name: "Stornieren" }).click();

    await expect(page.getByText("Belegung stornieren?")).toBeVisible();
    await expect(page.getByRole("button", { name: "Stornieren", exact: true }).last()).toBeVisible();
  });
});
