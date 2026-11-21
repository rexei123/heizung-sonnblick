import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Tagesplan eines Allgemeinbereichs (21.11.2026).
 *
 * **Was hier geprüft wird und am Endpunkt nicht geprüft werden kann:**
 *
 * 1. Das Formular steht beim Bereich und **nicht** beim Gästezimmer.
 * 2. Eine Überschneidung wird **vor** dem Speichern abgefangen — es geht
 *    kein `PUT` hinaus. Das ist die Zusage des Betreibers („Validierung
 *    Zod + Pydantic"): der Fehler soll beim Tippen auffallen, nicht nach
 *    einer Netzrunde.
 * 3. Solange ein Plan steht, sagt das Betriebszeit-Formular, dass es
 *    gerade **nicht** wirkt. Ohne diesen Satz stünden dort zwei Uhrzeiten
 *    ohne Wirkung (§5.77), und man würde den Fehler woanders suchen.
 * 4. „24:00" bleibt „24:00" und wird nicht zu „00:00".
 * 5. Die Rolle entscheidet über die Knöpfe — **beide** Richtungen
 *    ausdrücklich gesetzt, nicht über den Standard der Hülle.
 *
 * **Routen-Reihenfolge:** Playwright trifft die **zuletzt** registrierte
 * Route zuerst. Der Tagesplan-Weg steht deshalb hinter `rooms/3`.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-11-21T06:00:00Z",
  last_login_at: "2026-11-21T06:00:00Z",
};

const MITARBEITER = {
  ...ADMIN,
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
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
  updated_at: "2026-11-21T06:00:00Z",
};

const RT_GAST = { ...RT_BEREICH, id: 1, name: "Doppelzimmer", is_bookable: true };

/** Die Bar, mit gesetzter Betriebszeit 15:00–24:00. */
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
  updated_at: "2026-11-21T07:00:00Z",
  has_active_override: false,
  reference_zone_id: null,
  mean_temperature_c: 19.4,
  engine_setpoint_c: 21,
  ist_allgemeinbereich: true,
  betriebszeit_von: "15:00:00",
  betriebszeit_bis: "00:00:00",
};

const GASTZIMMER = {
  ...BAR,
  id: 4,
  number: "208",
  display_name: null,
  room_type_id: 1,
  floor: 2,
  ist_allgemeinbereich: false,
  betriebszeit_von: null,
  betriebszeit_bis: null,
};

const ZONE = {
  id: 9,
  room_id: 3,
  kind: "common_area" as const,
  name: "Barbereich",
  is_towel_warmer: false,
  health_state: "healthy" as const,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  active_override: null,
  mean_temperature_c: 19.4,
  engine_setpoint_c: 21,
  mean_temperature_at: "2026-11-21T07:50:00Z",
  geraete_luecke: "kein_stellglied" as const,
};

/** Der Plan aus dem Wunsch: 06:00–08:00 auf 25, 08:00–21:00 auf 22. */
const PLAN = {
  room_id: 3,
  fenster: [
    { id: 11, von: "06:00", bis: "08:00", temperatur: 25.0 },
    { id: 12, von: "08:00", bis: "21:00", temperatur: 22.0 },
  ],
};

const OHNE_PLAN = { room_id: 3, fenster: [] as unknown[] };

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

interface Aufbau {
  /** Die Körper aller `PUT`-Anfragen auf den Tagesplan, in Reihenfolge. */
  gesendet: unknown[];
}

async function mock(
  page: Page,
  { nutzer, plan, raum }: { nutzer?: unknown; plan?: unknown; raum?: unknown } = {},
): Promise<Aufbau> {
  const angemeldet = nutzer ?? ADMIN;
  const zimmer = raum ?? BAR;
  let stand = plan ?? OHNE_PLAN;
  const gesendet: unknown[] = [];

  await page.route("**/api/v1/**", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, angemeldet));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) => json(r, [BAR, GASTZIMMER]));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [RT_GAST, RT_BEREICH]));
  await page.route("**/api/v1/rooms/3", (r: Route) => json(r, zimmer));
  await page.route("**/api/v1/rooms/4", (r: Route) => json(r, GASTZIMMER));
  await page.route("**/api/v1/rooms/3/heating-zones", (r: Route) => json(r, [ZONE]));
  await page.route("**/api/v1/rooms/4/heating-zones", (r: Route) => json(r, []));
  await page.route("**/api/v1/rooms/*/engine-trace*", (r: Route) => json(r, []));
  // Hinter `rooms/3` — siehe Kopf.
  await page.route("**/api/v1/rooms/*/tagesplan", async (r: Route) => {
    if (r.request().method() === "PUT") {
      const koerper = r.request().postDataJSON();
      gesendet.push(koerper);
      const fenster = (koerper.fenster as { von: string; bis: string; temperatur: number }[]).map(
        (f, i) => ({ id: 100 + i, ...f }),
      );
      stand = { room_id: 3, fenster };
      return json(r, stand);
    }
    return json(r, stand);
  });
  return { gesendet };
}

test.describe("Tagesplan", () => {
  test("ohne Plan steht da, dass die Betriebszeit gilt", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer/3");

    await expect(page.getByTestId("tagesplan-form")).toBeVisible();
    await expect(page.getByTestId("tagesplan-leer")).toContainText("Kein Tagesplan");
    // Die Gegenprobe: ohne Fenster darf die Betriebszeit **nicht**
    // behaupten, sie wirke nicht.
    await expect(page.getByTestId("betriebszeit-tagesplan-hinweis")).toHaveCount(0);
  });

  test("der gespeicherte Plan steht in der Tabelle, mit Tagesleiste", async ({ page }) => {
    await mock(page, { plan: PLAN });
    await page.goto("/zimmer/3");

    await expect(page.getByTestId("tagesplan-von-0")).toHaveValue("06:00");
    await expect(page.getByTestId("tagesplan-bis-0")).toHaveValue("08:00");
    await expect(page.getByTestId("tagesplan-temperatur-0")).toHaveValue("25");
    await expect(page.getByTestId("tagesplan-von-1")).toHaveValue("08:00");
    await expect(page.getByTestId("tagesplan-temperatur-1")).toHaveValue("22");
    await expect(page.getByTestId("tagesplan-leiste")).toBeVisible();
  });

  test("solange ein Plan steht, sagt die Betriebszeit dass sie nicht wirkt", async ({ page }) => {
    await mock(page, { plan: PLAN });
    await page.goto("/zimmer/3");

    const hinweis = page.getByTestId("betriebszeit-tagesplan-hinweis");
    await expect(hinweis).toBeVisible();
    await expect(hinweis).toContainText("Tagesplan");
    // Und die Uhrzeiten stehen weiter da — sie sind nicht gelöscht,
    // sondern ruhend. Wer den Plan löscht, hat sie wieder.
    await expect(page.getByTestId("betriebszeit-von")).toHaveValue("15:00");
  });

  test("ein Fenster hinzufügen und speichern schickt beide Fenster", async ({ page }) => {
    const aufbau = await mock(page, { plan: PLAN });
    await page.goto("/zimmer/3");

    await page.getByTestId("tagesplan-hinzufuegen").click();
    // Die neue Zeile ist mit dem Ende der vorigen vorbelegt (21:00).
    await expect(page.getByTestId("tagesplan-von-2")).toHaveValue("21:00");
    await page.getByTestId("tagesplan-bis-2").fill("23:00");
    await page.getByTestId("tagesplan-temperatur-2").fill("20");
    await page.getByTestId("tagesplan-speichern").click();

    await expect(page.getByTestId("tagesplan-meldung")).toContainText("gespeichert");
    expect(aufbau.gesendet).toHaveLength(1);
    expect(aufbau.gesendet[0]).toEqual({
      fenster: [
        { von: "06:00", bis: "08:00", temperatur: 25 },
        { von: "08:00", bis: "21:00", temperatur: 22 },
        { von: "21:00", bis: "23:00", temperatur: 20 },
      ],
    });
  });

  test("eine Überschneidung wird abgefangen, bevor etwas hinausgeht", async ({ page }) => {
    const aufbau = await mock(page, { plan: PLAN });
    await page.goto("/zimmer/3");

    // Das erste Fenster bis 10:00 ziehen — das zweite beginnt um 08:00.
    await page.getByTestId("tagesplan-bis-0").fill("10:00");
    await page.getByTestId("tagesplan-speichern").click();

    await expect(page.getByTestId("tagesplan-fehler")).toContainText("überschneiden");
    expect(aufbau.gesendet, "ein ungültiger Plan darf das Haus nicht erreichen").toHaveLength(0);
  });

  test("ein Fenster über Mitternacht wird abgefangen", async ({ page }) => {
    const aufbau = await mock(page);
    await page.goto("/zimmer/3");

    await page.getByTestId("tagesplan-hinzufuegen").click();
    await page.getByTestId("tagesplan-von-0").fill("23:00");
    await page.getByTestId("tagesplan-bis-0").fill("01:00");
    await page.getByTestId("tagesplan-temperatur-0").fill("20");
    await page.getByTestId("tagesplan-speichern").click();

    await expect(page.getByTestId("tagesplan-fehler")).toContainText("Mitternacht");
    expect(aufbau.gesendet).toHaveLength(0);
  });

  test("ein Sollwert ausserhalb der Geraetegrenzen wird abgefangen", async ({ page }) => {
    const aufbau = await mock(page);
    await page.goto("/zimmer/3");

    await page.getByTestId("tagesplan-hinzufuegen").click();
    await page.getByTestId("tagesplan-von-0").fill("06:00");
    await page.getByTestId("tagesplan-bis-0").fill("08:00");
    await page.getByTestId("tagesplan-temperatur-0").fill("35");
    await page.getByTestId("tagesplan-speichern").click();

    await expect(page.getByTestId("tagesplan-fehler")).toContainText("30");
    expect(aufbau.gesendet).toHaveLength(0);
  });

  test("ein Komma ist eine Zahl", async ({ page }) => {
    const aufbau = await mock(page);
    await page.goto("/zimmer/3");

    await page.getByTestId("tagesplan-hinzufuegen").click();
    await page.getByTestId("tagesplan-von-0").fill("06:00");
    await page.getByTestId("tagesplan-bis-0").fill("08:00");
    await page.getByTestId("tagesplan-temperatur-0").fill("22,5");
    await page.getByTestId("tagesplan-speichern").click();

    await expect(page.getByTestId("tagesplan-meldung")).toBeVisible();
    expect(aufbau.gesendet[0]).toEqual({
      fenster: [{ von: "06:00", bis: "08:00", temperatur: 22.5 }],
    });
  });

  test("bis 24:00 bleibt 24:00", async ({ page }) => {
    const aufbau = await mock(page);
    await page.goto("/zimmer/3");

    await page.getByTestId("tagesplan-hinzufuegen").click();
    await page.getByTestId("tagesplan-von-0").fill("15:00");
    await page.getByTestId("tagesplan-bis-0").fill("24:00");
    await page.getByTestId("tagesplan-temperatur-0").fill("22");
    await page.getByTestId("tagesplan-speichern").click();

    await expect(page.getByTestId("tagesplan-meldung")).toBeVisible();
    expect(aufbau.gesendet[0]).toEqual({
      fenster: [{ von: "15:00", bis: "24:00", temperatur: 22 }],
    });
    await expect(page.getByTestId("tagesplan-bis-0")).toHaveValue("24:00");
  });

  test("Plan loeschen schickt eine leere Liste", async ({ page }) => {
    const aufbau = await mock(page, { plan: PLAN });
    await page.goto("/zimmer/3");

    await page.getByTestId("tagesplan-loeschen").click();

    await expect(page.getByTestId("tagesplan-meldung")).toContainText("gelöscht");
    expect(aufbau.gesendet[0]).toEqual({ fenster: [] });
  });

  test("ein Gästezimmer hat kein Tagesplan-Formular", async ({ page }) => {
    await mock(page, { raum: GASTZIMMER });
    await page.goto("/zimmer/4");

    await expect(page.getByTestId("tagesplan-form")).toHaveCount(0);
    // Die Gegenprobe steht im ersten Test: beim Bereich ist es da.
    await expect(page.getByTestId("betriebszeit-form")).toHaveCount(0);
  });

  test("der Mitarbeiter sieht die Zeiten, aber keine Knoepfe", async ({ page }) => {
    await mock(page, { nutzer: MITARBEITER, plan: PLAN });
    await page.goto("/zimmer/3");

    await expect(page.getByTestId("tagesplan-von-0")).toHaveValue("06:00");
    await expect(page.getByTestId("tagesplan-speichern")).toHaveCount(0);
    await expect(page.getByTestId("tagesplan-hinzufuegen")).toHaveCount(0);
    await expect(page.getByTestId("tagesplan-entfernen-0")).toHaveCount(0);
    await expect(page.getByTestId("tagesplan-form")).toContainText(
      "Administratoren vorbehalten",
    );
  });

  test("der Administrator sieht die Knoepfe", async ({ page }) => {
    await mock(page, { nutzer: ADMIN, plan: PLAN });
    await page.goto("/zimmer/3");

    await expect(page.getByTestId("tagesplan-speichern")).toBeVisible();
    await expect(page.getByTestId("tagesplan-hinzufuegen")).toBeVisible();
  });

  test("eine Temperatur als String wirft die Seite nicht um", async ({ page }) => {
    // §5.93: ein `Decimal` ohne `field_serializer` kommt als String. Das
    // Feld **steht** im Serializer; diese Probe hält fest, dass der
    // Spiegel es trotzdem übersteht — am 18.11.2026 hat genau diese
    // Annahme die Relais-Karte gekostet.
    await mock(page, {
      plan: {
        room_id: 3,
        fenster: [{ id: 11, von: "06:00", bis: "08:00", temperatur: "25.0" }],
      },
    });
    await page.goto("/zimmer/3");

    await expect(page.getByTestId("tagesplan-temperatur-0")).toHaveValue("25");
    await expect(page.getByTestId("tagesplan-form")).toBeVisible();
  });

  test("die leere Seite Profile nennt den Weg zum Tagesplan", async ({ page }) => {
    await mock(page);
    await page.goto("/profile");

    // Ein Versprechen ohne Weg ist derselbe Fehler wie ein Schalter ohne
    // Wirkung: die Seite heißt „Profile" und der Plan steht am Zimmer.
    await expect(page.locator("body")).toContainText("Stammdaten");
    await expect(page.locator("body")).toContainText("Tagesplan");
  });
});
