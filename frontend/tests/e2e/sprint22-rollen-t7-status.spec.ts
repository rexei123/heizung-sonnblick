import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 22 T7 — der angehaltene Status.
 *
 * **Der Befund dahinter:** `sync_room_status` leitet den Zimmer-Status alle
 * 60 s aus den Belegungen ab — aber **nicht** bei „Reinigung“ und
 * „Gesperrt“ (`occupancy_service.py:242`). Diese zwei Werte halten den
 * Abgleich an, und das stand nirgends: das Feld hiess „Status (manuell)“,
 * die Liste zeigte den Status wie jeden anderen, und in der Zimmer-Kopfzeile
 * stand gar nichts.
 *
 * Ein angehaltenes Zimmer darf nicht lautlos sein (Hotelier, 14.10.2026).
 * Drei Stellen, drei Pruefungen:
 *  1. Das Feld sagt, dass es automatisch gesetzt wird — und welche zwei
 *     Werte die Ausnahme sind.
 *  2. Diese zwei Werte verlangen eine Bestaetigung; Abbrechen laesst den
 *     Status stehen. Die anderen drei gehen ohne Rueckfrage durch, weil sie
 *     binnen einer Minute ueberschrieben werden.
 *  3. Liste und Kopfzeile nennen den angehaltenen Zustand.
 *
 * Rolle: ausdruecklich `admin`, weil das Formular sonst nur lesbar ist
 * (T4/T5). Die Standard-Huelle aus `fixtures.ts` liefert denselben Wert —
 * hier steht er trotzdem, damit die Pruefung nicht davon abhaengt.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-14T06:00:00Z",
  last_login_at: "2026-10-14T06:00:00Z",
};

type Status = "occupied" | "vacant" | "reserved" | "cleaning" | "blocked";

function roomMock(id: number, nummer: string, status: Status): Record<string, unknown> {
  return {
    id,
    number: nummer,
    display_name: null,
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

const RAUMTYP = {
  id: 1,
  name: "Standard",
  beds: 2,
  area_m2: 20,
  occupied_setpoint: "21",
  vacant_setpoint: "18",
  night_setback_offset: "2",
  frost_protection_setpoint: "8",
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

async function mockApi(page: Page, zimmer: Record<string, unknown>[]): Promise<void> {
  // Catch-all zuerst: Playwright trifft die zuletzt registrierte Route.
  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ADMIN),
    });
  });

  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([RAUMTYP]),
    });
  });

  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(zimmer),
    });
  });

  for (const r of zimmer) {
    const id = r.id as number;
    await page.route(
      new RegExp(".*/api/v1/rooms/" + id + "(\\?.*)?$"),
      async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(r),
        });
      },
    );
  }
}

test.describe("Sprint 22 T7 — angehaltener Status", () => {
  test("statusfeld_nennt_die_automatik_und_ihre_ausnahme", async ({ page }) => {
    await mockApi(page, [roomMock(101, "101", "occupied")]);
    await page.goto("/zimmer/101");

    // Die Beschriftung war „Status (manuell)“ — eine Aufforderung zur
    // Pflege eines Feldes, das sich selbst setzt.
    await expect(page.getByText("Status (automatisch aus Belegungen)")).toBeVisible();
    await expect(page.getByText("Status (manuell)")).toHaveCount(0);

    // Der Hinweis nennt beide Haelften: was ueberschrieben wird und was
    // stehen bleibt.
    await expect(page.getByText(/wird binnen einer Minute\s+überschrieben/)).toBeVisible();
    await expect(
      page.getByText(/halten den\s+Abgleich für dieses Zimmer an/),
    ).toBeVisible();
  });

  test("gesperrt_verlangt_bestaetigung_abbrechen_laesst_den_status_stehen", async ({
    page,
  }) => {
    await mockApi(page, [roomMock(101, "101", "occupied")]);
    await page.goto("/zimmer/101");

    const feld = page.locator("#r-status");
    await expect(feld).toHaveValue("occupied");

    await feld.selectOption("blocked");
    await expect(page.getByText("Automatik anhalten?")).toBeVisible();
    await expect(
      page.getByText(/Anreisen und Abreisen wirken dann nicht mehr/),
    ).toBeVisible();

    // Abbrechen: der Status bleibt, wo er war. Das Auswahlfeld ist
    // kontrolliert — ohne `setStatus` springt es zurueck.
    await page.getByRole("button", { name: "Abbrechen" }).click();
    await expect(page.getByText("Automatik anhalten?")).toHaveCount(0);
    await expect(feld).toHaveValue("occupied");

    // Zweiter Anlauf, diesmal bestaetigt.
    await feld.selectOption("blocked");
    await page.getByRole("button", { name: "Automatik anhalten" }).click();
    await expect(page.getByText("Automatik anhalten?")).toHaveCount(0);
    await expect(feld).toHaveValue("blocked");
  });

  test("reinigung_fragt_auch_frei_und_belegt_nicht", async ({ page }) => {
    await mockApi(page, [roomMock(101, "101", "occupied")]);
    await page.goto("/zimmer/101");

    const feld = page.locator("#r-status");

    await feld.selectOption("cleaning");
    await expect(page.getByText("Automatik anhalten?")).toBeVisible();
    // Die Reinigungs-Fassung sagt nichts ueber An- und Abreisen — ein
    // Zimmer in Reinigung ist ohnehin zwischen zwei Gaesten.
    await expect(page.getByText(/Anreisen und Abreisen wirken/)).toHaveCount(0);
    await page.getByRole("button", { name: "Automatik anhalten" }).click();
    await expect(feld).toHaveValue("cleaning");

    // Zurueck auf einen abgeleiteten Wert: keine Rueckfrage, weil die
    // Eingabe folgenlos ist.
    await feld.selectOption("vacant");
    await expect(page.getByText("Automatik anhalten?")).toHaveCount(0);
    await expect(feld).toHaveValue("vacant");

    await feld.selectOption("reserved");
    await expect(page.getByText("Automatik anhalten?")).toHaveCount(0);
    await expect(feld).toHaveValue("reserved");
  });

  test("liste_zeigt_angehaltene_zimmer", async ({ page }) => {
    await mockApi(page, [
      roomMock(101, "101", "occupied"),
      roomMock(102, "102", "cleaning"),
      roomMock(103, "103", "blocked"),
    ]);
    await page.goto("/zimmer");

    await expect(page.getByText("· Automatik angehalten")).toHaveCount(2);

    const zeile = (nummer: string) =>
      page.getByRole("row").filter({ hasText: new RegExp("^" + nummer) });
    await expect(zeile("102").getByText("· Automatik angehalten")).toBeVisible();
    await expect(zeile("103").getByText("· Automatik angehalten")).toBeVisible();
    await expect(zeile("101").getByText("· Automatik angehalten")).toHaveCount(0);
  });

  test("kopfzeile_nennt_den_angehaltenen_status", async ({ page }) => {
    await mockApi(page, [roomMock(103, "103", "blocked")]);
    await page.goto("/zimmer/103");

    const hinweis = page.getByRole("status").filter({ hasText: "Automatik angehalten" });
    await expect(hinweis).toBeVisible();
    await expect(hinweis).toContainText("Gesperrt");
    await expect(hinweis).toContainText(
      /Anreisen\s+und Abreisen setzen den Status nicht mehr/,
    );
  });

  test("kopfzeile_schweigt_bei_laufender_automatik", async ({ page }) => {
    await mockApi(page, [roomMock(101, "101", "occupied")]);
    await page.goto("/zimmer/101");

    // Sanity, damit das Fehlen nicht am nicht geladenen Zimmer liegt.
    await expect(page.getByRole("heading", { level: 1, name: "Zimmer 101" })).toBeVisible();
    await expect(page.getByText("Automatik angehalten")).toHaveCount(0);
  });
});
