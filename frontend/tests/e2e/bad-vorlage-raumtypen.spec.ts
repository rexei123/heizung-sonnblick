import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Raumtypen-Seite: der Raumtyp „Bad" ist als Vorlage erkennbar
 * (18.10.2026).
 *
 * **Warum das ein eigener Test ist.** Diesem Raumtyp sind **keine Zimmer**
 * zugeordnet — er sieht damit aus wie ein verwaister Eintrag, und der
 * Löschen-Knopf ist nicht gesperrt (genau weil keine Zimmer hängen). Wer
 * ihn löscht, nimmt allen Bädern im Haus ihre Werte: nachts 19 statt 22.
 * Die Seite muss das sagen, bevor es passiert.
 *
 * Drei Prüfungen: Kennzeichnung in der Liste, Hinweis in der Bearbeitung,
 * und die Warnung im Löschen-Dialog mit ihrer Folge.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-18T06:00:00Z",
  last_login_at: "2026-10-18T06:00:00Z",
};

function raumtyp(id: number, name: string): Record<string, unknown> {
  return {
    id,
    name,
    description: null,
    is_bookable: name !== "Bad",
    default_t_occupied: name === "Bad" ? "22.0" : "21.0",
    default_t_vacant: "18.0",
    default_t_night: name === "Bad" ? "22.0" : "19.0",
    max_temp_celsius: name === "Bad" ? "25.0" : "24.0",
    min_temp_celsius: name === "Bad" ? "18.0" : "16.0",
    treat_unoccupied_as_vacant_after_hours: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-18T06:00:00Z",
  };
}

async function mockApi(page: Page): Promise<void> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  await page.route("**/api/v1/**", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) =>
    json(r, [raumtyp(1, "Doppelzimmer"), raumtyp(2, "Suite"), raumtyp(3, "Bad")]),
  );
}

test.describe("Raumtypen — Bad als Vorlage", () => {
  test("liste_kennzeichnet_die_vorlage", async ({ page }) => {
    await mockApi(page);
    await page.goto("/raumtypen");

    await expect(page.getByText("· Vorlage für Bad-Zonen")).toHaveCount(1);
    const badZeile = page.getByRole("listitem").filter({ hasText: "Bad" });
    await expect(badZeile.getByText("· Vorlage für Bad-Zonen")).toBeVisible();

    // Und nicht an den anderen beiden.
    const dzZeile = page.getByRole("listitem").filter({ hasText: "Doppelzimmer" });
    await expect(dzZeile.getByText("Vorlage")).toHaveCount(0);
  });

  test("bearbeiten_zeigt_den_hinweis_mit_der_zonen_art", async ({ page }) => {
    await mockApi(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Bad" }).click();

    const hinweis = page.getByRole("note");
    await expect(hinweis).toContainText("Vorlage für alle Bad-Zonen");
    await expect(hinweis).toContainText("kind=bathroom");
    // Der Satz, der die Verwirrung aufloest: keine Zimmer, trotzdem wirksam.
    await expect(hinweis).toContainText("nicht für Zimmer dieses Typs");
  });

  test("loeschen_warnt_mit_der_folge", async ({ page }) => {
    await mockApi(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Bad" }).click();
    await page.getByRole("button", { name: /Löschen/ }).click();

    const dialog = page.getByText("Raumtyp löschen?");
    await expect(dialog).toBeVisible();
    // Die Folge in Zahlen, nicht als Allgemeinheit.
    await expect(page.getByText(/folgen die Bäder wieder dem Zimmertyp/)).toBeVisible();
    await expect(page.getByText(/19 °C statt 22 °C/)).toBeVisible();
  });

  test("anderer_raumtyp_warnt_nicht_besonders", async ({ page }) => {
    await mockApi(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Doppelzimmer" }).click();
    await expect(page.getByRole("note")).toHaveCount(0);

    await page.getByRole("button", { name: /Löschen/ }).click();
    await expect(page.getByText("Raumtyp löschen?")).toBeVisible();
    await expect(page.getByText(/folgen die Bäder/)).toHaveCount(0);
  });
});
