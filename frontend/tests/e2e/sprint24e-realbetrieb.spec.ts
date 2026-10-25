import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 24e (PR B) — die Befunde aus dem Realbetrieb in der Oberfläche.
 *
 * Fünf Dinge, die alle nur im Browser zu sehen sind:
 *
 * 1. **Die Betriebszeit meldet ihr Ergebnis sichtbar.** Der Betreiber hat
 *    am 25.10.2026 gemeldet, es sei „keine Bestätigung" gekommen — ein
 *    Satz in der kleinsten Schriftgröße unter einem Formular ist von
 *    „nichts passiert" nicht zu unterscheiden, und ein Fehler erst recht
 *    nicht.
 * 2. **Kein Zustand aus einem anderen Zimmer.** Der App-Router behält die
 *    Komponente beim Wechsel von `/zimmer/3` auf `/zimmer/4`.
 * 3. **Stammdaten eines Allgemeinbereichs** nennen keinen
 *    Belegungsstatus.
 * 4. **Einheitliche Begriffe** in der Raumtyp-Liste und auf der globalen
 *    Seite.
 * 5. **Die Zeitzone steht am Verlauf** — in der Umstellungsnacht trägt die
 *    Achse zweimal „02:00".
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-25T06:00:00Z",
  last_login_at: "2026-10-25T06:00:00Z",
};

/** Die Bar — Bereich mit Betriebszeit. */
const BAR = {
  id: 3,
  number: "Bar",
  display_name: "Barbereich",
  room_type_id: 5,
  floor: 0,
  orientation: null,
  status: "vacant" as const,
  guest_override_blocked: false,
  notes: null,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-25T07:00:00Z",
  has_active_override: false,
  reference_zone_id: null,
  mean_temperature_c: 19.4,
  engine_setpoint_c: 21,
  ist_allgemeinbereich: true,
  betriebszeit_von: "15:00:00",
  betriebszeit_bis: "00:00:00",
};

/** Die Rezeption — Bereich **ohne** Betriebszeit. */
const REZEPTION = {
  ...BAR,
  id: 4,
  number: "Rezeption",
  display_name: "Eingang",
  room_type_id: 6,
  betriebszeit_von: null,
  betriebszeit_bis: null,
};

const GASTZIMMER = {
  ...BAR,
  id: 7,
  number: "208",
  display_name: null,
  room_type_id: 1,
  ist_allgemeinbereich: false,
  betriebszeit_von: null,
  betriebszeit_bis: null,
};

const RT_BEREICH = {
  id: 5,
  name: "Raum intern",
  description: null,
  is_bookable: false,
  default_t_occupied: "21.0",
  default_t_vacant: "21.0",
  default_t_night: "17.0",
  max_temp_celsius: "25.0",
  min_temp_celsius: "16.0",
  treat_unoccupied_as_vacant_after_hours: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-24T06:00:00Z",
};

const RT_GAST = {
  ...RT_BEREICH,
  id: 1,
  name: "Doppelzimmer",
  is_bookable: true,
  default_t_vacant: "18.0",
  default_t_night: "19.0",
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mock(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) =>
    json(r, [BAR, REZEPTION, GASTZIMMER]),
  );
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [RT_GAST, RT_BEREICH]));
  await page.route(/.*\/api\/v1\/room-types\/sollwert-wirksamkeit$/, (r: Route) => json(r, []));
  for (const raum of [BAR, REZEPTION, GASTZIMMER]) {
    await page.route(`**/api/v1/rooms/${raum.id}`, (r: Route) => {
      if (r.request().method() !== "GET") return r.fallback();
      return json(r, raum);
    });
    await page.route(`**/api/v1/rooms/${raum.id}/heating-zones`, (r: Route) => json(r, []));
    await page.route(`**/api/v1/rooms/${raum.id}/engine-trace*`, (r: Route) => json(r, []));
  }
}

test.describe("Sprint 24e — Befunde aus dem Realbetrieb", () => {
  test("die Betriebszeit meldet ihren Erfolg sichtbar", async ({ page }) => {
    await mock(page);
    await page.route("**/api/v1/rooms/4/betriebszeit", (r: Route) =>
      json(r, { ...REZEPTION, betriebszeit_von: "07:00:00", betriebszeit_bis: "22:00:00" }),
    );

    await page.goto("/zimmer/4");
    await expect(page.getByTestId("betriebszeit-form")).toBeVisible();

    await page.getByTestId("betriebszeit-von").fill("07:00");
    await page.getByTestId("betriebszeit-bis").fill("22:00");
    await page.getByTestId("betriebszeit-speichern").click();

    const meldung = page.getByTestId("betriebszeit-meldung");
    await expect(meldung).toBeVisible();
    await expect(meldung).toContainText("gespeichert");
    // Als Meldung und nicht als Fußnote: `role="status"` liest ein
    // Screenreader vor, und die Umrandung sieht man auch ohne zu suchen.
    await expect(meldung).toHaveAttribute("role", "status");
  });

  test("ein abgewiesenes Speichern ist nicht zu übersehen", async ({ page }) => {
    // **Der Kern des Befundes:** „Fehler müssen sichtbar gemeldet werden,
    // nie still." Vorher war das eine 11-px-Zeile in Rot.
    await mock(page);
    await page.route("**/api/v1/rooms/4/betriebszeit", (r: Route) =>
      json(
        r,
        { detail: "Betriebszeit braucht Beginn und Ende — oder beides leer." },
        422,
      ),
    );

    await page.goto("/zimmer/4");
    await page.getByTestId("betriebszeit-von").fill("07:00");
    await page.getByTestId("betriebszeit-speichern").click();

    const fehler = page.getByTestId("betriebszeit-fehler");
    await expect(fehler).toBeVisible();
    await expect(fehler).toHaveAttribute("role", "alert");
    await expect(fehler).toContainText("nicht");
    await expect(fehler).toContainText("Beginn und Ende");
    // Und keine Erfolgsmeldung daneben.
    await expect(page.getByTestId("betriebszeit-meldung")).toHaveCount(0);
  });

  test("der Wechsel des Zimmers nimmt die Zeiten nicht mit", async ({ page }) => {
    // Dieselbe Fehlerklasse wie beim Raumtyp-Formular (PR A): der Router
    // behält die Komponente, `useState` läuft nur bei der Montage.
    await mock(page);

    await page.goto("/zimmer/3");
    await expect(page.getByTestId("betriebszeit-von")).toHaveValue("15:00");

    // Über die Zimmerliste wechseln — dieselbe Route, andere ID.
    await page.goto("/zimmer/4");

    await expect(page.getByTestId("betriebszeit-von")).toHaveValue("");
    await expect(page.getByTestId("betriebszeit-bis")).toHaveValue("");
  });

  test("die Stammdaten eines Bereichs nennen keinen Belegungsstatus", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer/3");

    const auswahl = page.getByTestId("r-status");
    await expect(auswahl).toHaveAttribute("data-bereich", "true");
    await expect(auswahl.locator("option")).toHaveCount(2);
    await expect(auswahl.locator('option[value="vacant"]')).toHaveText(
      "Allgemeinbereich (in Betrieb)",
    );
    await expect(auswahl.locator('option[value="blocked"]')).toHaveText(
      "Gesperrt (außer Betrieb)",
    );
    await expect(page.getByTestId("r-status-hinweis")).toContainText("keine Belegung");
  });

  test("ein Gästezimmer behält alle fünf Status", async ({ page }) => {
    // Die Gegenprobe — sonst wäre der Test oben auch grün, wenn jede
    // Zimmerseite nur zwei Zustände anbietet.
    await mock(page);
    await page.goto("/zimmer/7");

    const auswahl = page.getByTestId("r-status");
    await expect(auswahl).toHaveAttribute("data-bereich", "false");
    await expect(auswahl.locator("option")).toHaveCount(6);
    await expect(page.getByTestId("r-status-hinweis")).toContainText("aus den Belegungen");
  });

  test("die Raumtyp-Liste nennt Betrieb und Absenkung", async ({ page }) => {
    await mock(page);
    await page.goto("/raumtypen");

    const bereich = page.getByRole("listitem").filter({ hasText: "Raum intern" });
    await expect(bereich).toContainText("Betrieb 21.0°");
    await expect(bereich).toContainText("Absenkung 17.0°");
    await expect(bereich).not.toContainText("Belegt");

    // Und ein Gästezimmer-Raumtyp bleibt bei Belegt/Frei.
    const gast = page.getByRole("listitem").filter({ hasText: "Doppelzimmer" });
    await expect(gast).toContainText("Belegt 21.0°");
    await expect(gast).toContainText("Frei 18.0°");
  });

  test("die globale Seite schreibt Singular im Singular", async ({ page }) => {
    await mock(page);
    await page.route(/.*\/api\/v1\/rule-configs\/global$/, (r: Route) =>
      json(r, {
        id: 1,
        t_occupied: null,
        t_vacant: null,
        t_night: "19.0",
        night_start: "20:00:00",
        night_end: "06:00:00",
        preheat_minutes_before_checkin: 60,
        created_at: "2026-04-01T10:00:00Z",
        updated_at: "2026-10-21T10:00:00Z",
      }),
    );
    await page.route(/.*\/api\/v1\/rule-configs\/global\/nutzung$/, (r: Route) =>
      json(r, [
        {
          feld: "night_start",
          gesetzt: true,
          raumtypen_nutzen: 1,
          raumtypen_eigen: 1,
          zimmer_eigen: 1,
        },
      ]),
    );

    await page.goto("/einstellungen/temperaturen-zeiten");

    // „1 Zimmer hat … und bleibt unberührt" — beide Verben im Singular.
    const zeile = page.getByText(/1 Zimmer hat eine eigene Einstellung und bleibt unberührt/);
    await expect(zeile).toBeVisible();
    await expect(page.getByText(/1 Raumtyp nimmt diesen Wert, 1 hat einen eigenen/)).toBeVisible();
  });

  test("der Verlauf nennt die Zeitzone", async ({ page }) => {
    // In der Umstellungsnacht trägt die Achse zweimal „02:00". Die Linie
    // ist dort lückenlos — nur die Beschriftung wiederholt sich, und ohne
    // diesen Hinweis sieht das wie ein Fehler aus.
    await mock(page);
    const jetzt = Date.now();
    await page.route(/.*\/api\/v1\/rooms\/3\/history(\?.*)?$/, (r: Route) =>
      json(r, {
        room_id: 3,
        range: "24h",
        bucket_minutes: 10,
        range_from: new Date(jetzt - 24 * 3600 * 1000).toISOString(),
        range_to: new Date(jetzt).toISOString(),
        timezone: "Europe/Vienna",
        night_window: null,
        zones: [
          {
            zone_id: 9,
            name: "Barbereich",
            kind: "common_area",
            points: [
              {
                t: new Date(jetzt - 3600 * 1000).toISOString(),
                temperature: 19.4,
                setpoint: 21,
              },
              { t: new Date(jetzt).toISOString(), temperature: 19.6, setpoint: 21 },
            ],
          },
        ],
        night_bands: [],
      }),
    );

    await page.goto("/zimmer/3");
    await page.getByRole("button", { name: "Verlauf", exact: true }).click();

    await expect(page.getByTestId("verlauf-zeitzone")).toContainText("Zeiten in");
  });
});
