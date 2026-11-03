import { expect, test, type Page, type Route } from "./fixtures";

/**
 * Die drei Geräte-Aktionen auf der Zimmerseite tragen schwarze Schrift
 * (03.11.2026).
 *
 * Vorgabe des Betreibers vom 31.10.2026 („Schrift schwarz"), am
 * 03.11.2026 von der Zimmerliste auf diese Stelle ausgedehnt.
 *
 * **Es sind drei und nicht zwei.** „Tauschen", „Stilllegen" und
 * „Trennen" stehen nebeneinander in derselben Zeile und sahen gleich
 * aus — bis man mit der Maus darüberfuhr: dann wurden sie in **drei
 * verschiedene Farben** umgefärbt. „Tauschen" nahm dabei die
 * **Primärfarbe**, also genau die, die die Vorgabe ausschließt. Mein
 * erster Bericht nannte nur die zwei roten, weil ich nach
 * `hover:text-error` gesucht hatte und nicht nach der Familie.
 *
 * Geprüft wird:
 *
 * 1. **In Ruhe** tragen alle drei das Text-Token, und zwar dasselbe.
 * 2. **Beim Überfahren bleibt die Farbe stehen** — einzeln für jede der
 *    drei, weil jede vorher ihre eigene hatte. Ein Test, der nur eine
 *    prüft, besteht auch dann, wenn zwei weiter umfärben.
 * 3. **Die Unterstreichung kommt beim Überfahren** und trägt seither den
 *    Hinweis, dass hier etwas anklickbar ist.
 * 4. **Die Symbole erben die Farbe.**
 *
 * **Die Farben kommen zur Laufzeit aus `globals.css`**, nicht als Hex in
 * den Test: eine Zahl hier wäre eine zweite Wahrheit und beim ersten
 * Nachjustieren am Token falsch. Der Helfer dafür steht auch in
 * `zimmerliste-knopffarbe.spec.ts` — bei einem dritten Verbraucher
 * gehört er nach `fixtures.ts`.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-11-03T06:00:00Z",
  last_login_at: "2026-11-03T06:00:00Z",
};

const ROOM = {
  id: 101,
  number: "101",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "occupied",
  guest_override_blocked: false,
  guest_block_bis_checkout: false,
  ist_allgemeinbereich: false,
  has_active_override: false,
  uebersteuerung_quelle: null,
  uebersteuerung_ende: null,
  boost_moeglich: false,
  boost_grund: "kein_nachtfenster",
  boost_hinweis: null,
  boost_ende: null,
  notes: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-11-03T06:00:00Z",
  reference_zone_id: 201,
  mean_temperature_c: 20.4,
  engine_setpoint_c: 21,
};

const ZONE = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

const DEVICE = {
  id: 11,
  dev_eui: "70b3d52dd3034de4",
  app_eui: null,
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "Vicki",
  label: "Vicki Schlafzimmer 101",
  heating_zone_id: ZONE.id,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: "2026-11-03T05:30:00Z",
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-11-03T06:00:00Z",
};

const HARDWARE_STATUS = {
  device_id: 11,
  grenzen_gesetzt: true,
  min_setpoint_c: "15.0",
  max_setpoint_c: "25.0",
  last_success_at: "2026-11-03T05:00:00Z",
};

/** Die drei Aktionen, so wie sie am Gerät stehen. */
const AKTIONEN = [
  "Thermostat tauschen",
  "Thermostat stilllegen",
  "Gerät von Heizzone trennen",
];

async function mockApi(page: Page): Promise<void> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  // Catch-all zuerst: Playwright trifft die zuletzt registrierte Route
  // zuerst, der Rückhalt steht also oben.
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (r: Route) => json(r, ROOM));
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (r: Route) =>
    json(r, [ZONE]),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (r: Route) =>
    json(r, HARDWARE_STATUS),
  );
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (r: Route) => json(r, [DEVICE]));
}

/**
 * Zur Zimmerseite und in den Reiter „Geräte" — dort stehen die drei
 * Aktionen. Der erste Reiter zeigt sie nicht.
 */
async function zumGeraeteReiter(page: Page): Promise<void> {
  await page.goto("/zimmer/101");
  await page.getByRole("button", { name: "Geräte", exact: true }).click();
}

/** Ein Token aus `globals.css`, als `rgb(...)` wie `getComputedStyle` es liefert. */
async function token(page: Page, name: string): Promise<string> {
  return page.evaluate((n: string) => {
    const hex = getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgb(${r}, ${g}, ${b})`;
  }, name);
}

test.describe("Geräte-Aktionen auf der Zimmerseite: Schrift schwarz", () => {
  test("alle drei tragen in Ruhe das Text-Token", async ({ page }) => {
    await mockApi(page);
    await zumGeraeteReiter(page);

    const schwarz = await token(page, "--color-text-primary");
    const rose = await token(page, "--color-primary");
    const rot = await token(page, "--color-error");
    // Die Probe hat nur Wert, wenn die drei Token verschieden sind.
    expect(new Set([schwarz, rose, rot]).size).toBe(3);

    for (const name of AKTIONEN) {
      const knopf = page.getByRole("button", { name, exact: true });
      await expect(knopf).toBeVisible();
      await expect(knopf).toHaveCSS("color", schwarz);
    }
  });

  test("beim Überfahren bleibt die Farbe stehen — bei jeder der drei", async ({
    page,
  }) => {
    // Einzeln, nicht stellvertretend: vorher hatte jede ihre eigene
    // Hover-Farbe („Tauschen" die Primärfarbe, die beiden anderen Rot).
    await mockApi(page);
    await zumGeraeteReiter(page);

    const schwarz = await token(page, "--color-text-primary");

    for (const name of AKTIONEN) {
      const knopf = page.getByRole("button", { name, exact: true });
      await knopf.hover();
      await expect(knopf).toHaveCSS("color", schwarz);
    }
  });

  test("die Unterstreichung kommt erst beim Überfahren", async ({ page }) => {
    // Sie trägt jetzt allein den Hinweis „anklickbar" — fällt sie weg,
    // ist der Knopf von gewöhnlichem Text nicht zu unterscheiden.
    await mockApi(page);
    await zumGeraeteReiter(page);

    const knopf = page.getByRole("button", { name: "Thermostat tauschen", exact: true });
    await expect(knopf).toHaveCSS("text-decoration-line", "none");

    await knopf.hover();
    await expect(knopf).toHaveCSS("text-decoration-line", "underline");
  });

  test("die Symbole erben die Farbe der Schrift", async ({ page }) => {
    await mockApi(page);
    await zumGeraeteReiter(page);

    const schwarz = await token(page, "--color-text-primary");

    for (const name of AKTIONEN) {
      const symbol = page
        .getByRole("button", { name, exact: true })
        .locator("span.material-symbols-outlined");
      await expect(symbol).toHaveCSS("color", schwarz);
    }
  });
});
