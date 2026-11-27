import { expect, test } from "./fixtures";

/**
 * Hinweis „Abreise überschritten" auf dem Dashboard (27.11.2026).
 *
 * **Der Fall steht im Handbuch:** ein Gast bleibt länger, niemand ändert
 * das Abreisedatum, und die Steuerung setzt das Zimmer am ursprünglichen
 * Abreisetag auf frei. Der Hinweis ist der Punkt, an dem die Rezeption es
 * sieht, bevor der Gast abends im kühlen Zimmer steht.
 *
 * **Eigene Datei und nicht in `sprint-14c-dashboard`.** Dort wird die
 * Kachelzahl geprüft; dieser Hinweis ist keine Kachel, und ein Test, der
 * Kacheln zählt, würde durch jede neue Zeile hier gestört.
 *
 * Der Zod-Spiegel hat für `abreise_zimmer` ein `.default([])`. Die Mocks
 * der anderen Dateien bleiben deshalb gültig — das ist Absicht: ein neues
 * Hinweisfeld darf nicht die ganze Seite leer lassen, die Kacheln hängen
 * an derselben Antwort.
 */

const BASIS = {
  rooms_occupied: 1,
  rooms_total: 30,
  avg_temperature_celsius: 21.4,
  devices_online: 4,
  devices_assigned: 4,
  devices_pool: 0,
  active_overrides: 0,
  zones_window_open: 0,
  last_engine_tick: new Date(Date.now() - 60_000).toISOString(),
  battery_low_count: 0,
  valve_check_count: 0,
  room_too_warm_count: 0,
  funkempfang_stufe: "online" as const,
  funkempfang_letzte_meldung: new Date(Date.now() - 60_000).toISOString(),
  funkempfang_alter_min: 1,
  funkempfang_meldungen_10min: 104,
  fenstererkennung_aktiv: false,
  befehle_nicht_angenommen: 0,
  relais_zonen_stumm: 0,
  relais_zonen_stille_min: null,
  platte_prozent: 64,
  platte_frei_gb: 27.0,
  platte_warnt: false,
  abreise_zimmer: [] as unknown[],
};

async function mock(
  page: import("@playwright/test").Page,
  zimmer: unknown[],
): Promise<void> {
  await page.route(
    "**/api/v1/integrations/occupancy-import/log",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "green",
          last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
          expected_by_local: "12:00",
          expected_by_local_label: "12:00 MESZ",
          today_received: true,
          imports: [],
        }),
      });
    },
  );
  await page.route("**/api/v1/dashboard/kpi", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...BASIS, abreise_zimmer: zimmer }),
    });
  });
}

test.describe("Abreise überschritten", () => {
  test("ohne verstrichene Abreise steht kein Hinweis", async ({ page }) => {
    await mock(page, []);
    await page.goto("/");

    // Die Kacheln sind da — der Hinweis nicht. Beides prüfen, sonst
    // wäre der Test auch grün, wenn die Seite gar nicht geladen hat
    // (§5.55: eine leere Erwartung, die aus zwei Gründen erfüllt ist).
    await expect(page.getByText("Belegte Zimmer")).toBeVisible();
    await expect(page.getByTestId("abreise-hinweis")).toHaveCount(0);
  });

  test("der Hinweis nennt Zimmer, Alter und die Spur", async ({ page }) => {
    await mock(page, [
      { room_id: 12, zimmer: "107", stunden_her: 2, zeichen: "drehrad" },
      { room_id: 13, zimmer: "209", stunden_her: 5, zeichen: "keines" },
    ]);
    await page.goto("/");

    const hinweis = page.getByTestId("abreise-hinweis");
    await expect(hinweis).toBeVisible();
    await expect(hinweis).toContainText("107");
    await expect(hinweis).toContainText("vor 2 Stunden");
    await expect(hinweis).toContainText("jemand hat am Thermostat gedreht");
    await expect(hinweis).toContainText("209");
    await expect(hinweis).toContainText("vor 5 Stunden");

    // Ein Zimmer ohne Spur trägt **keinen** beruhigenden Zusatz. „Keine
    // Spur" wäre eine Beruhigung ohne Grund: die meisten Gäste drehen
    // nicht am Thermostat.
    await expect(page.getByTestId("abreise-hinweis-13")).not.toContainText(
      "Thermostat",
    );
  });

  test("Zimmer mit Spur stehen oben", async ({ page }) => {
    await mock(page, [
      { room_id: 13, zimmer: "209", stunden_her: 1, zeichen: "keines" },
      { room_id: 12, zimmer: "107", stunden_her: 9, zeichen: "drehrad" },
    ]);
    await page.goto("/");

    // Die Reihenfolge der Antwort ist „jüngste Abreise zuerst"; die
    // Oberfläche zieht die belegten Fälle nach oben. Dort ist der
    // Verdacht nicht möglich, sondern belegt.
    const zeilen = page.locator('[data-testid^="abreise-hinweis-"]');
    await expect(zeilen).toHaveCount(2);
    await expect(zeilen.nth(0)).toContainText("107");
    await expect(zeilen.nth(1)).toContainText("209");
  });

  test("die Wege führen zum Zimmer und zur Belegungsliste", async ({
    page,
  }) => {
    await mock(page, [
      { room_id: 12, zimmer: "107", stunden_her: 2, zeichen: "uebersteuerung" },
    ]);
    await page.goto("/");

    // Der Hinweis sagt nicht nur, dass etwas offen ist, sondern wo man
    // es erledigt — die Belegung ist der dauerhafte Weg, nicht die
    // Übersteuerung (Handbuch „Abreise verschiebt sich").
    await expect(
      page.getByTestId("abreise-hinweis").getByRole("link", { name: "107" }),
    ).toHaveAttribute("href", "/zimmer/12");
    await expect(
      page
        .getByTestId("abreise-hinweis")
        .getByRole("link", { name: "Abreise in der Belegung" }),
    ).toHaveAttribute("href", "/belegungen");
    await expect(page.getByTestId("abreise-hinweis")).toContainText(
      "Wunschtemperatur gesetzt",
    );
  });

  test("eine Abreise in dieser Stunde heisst nicht vor 0 Stunden", async ({
    page,
  }) => {
    await mock(page, [
      { room_id: 12, zimmer: "107", stunden_her: 0, zeichen: "keines" },
    ]);
    await page.goto("/");

    // Eine Abreise, die vor vierzig Minuten war, ist nicht „vor 0
    // Stunden" — das liest sich wie ein Fehler und kostet den Blick,
    // der prüfen soll, ob die Zahl stimmt.
    await expect(page.getByTestId("abreise-hinweis")).toContainText(
      "in dieser Stunde",
    );
  });
});
