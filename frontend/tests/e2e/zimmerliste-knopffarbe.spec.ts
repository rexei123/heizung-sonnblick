import { expect, test, type Page, type Route } from "./fixtures";

/**
 * Die Schrift der beiden Zeilen-Knöpfe ist schwarz, nicht Brand-Rosé
 * (03.11.2026).
 *
 * Vorgabe des Betreibers vom 31.10.2026: „Schrift schwarz". `ghost`
 * liefert aus dem Design-System `text-primary`; die Zimmerliste hebt das
 * auf (`ZEILEN_KNOPF_KLASSEN` in `app/zimmer/page.tsx`).
 *
 * **Geprüft wird die gerechnete Farbe, nicht die Klasse.** Eine
 * Klassen-Prüfung („enthält `text-text-primary`") besteht auch dann, wenn
 * die Klasse gar nicht greift — und greifen muss sie hier gegen das
 * `text-primary` der Variante, aufgelöst von `tailwind-merge` in `cn()`.
 * Genau diese Auflösung ist das Fragile; ein Test, der sie nicht
 * mitprüft, prüft das Falsche.
 *
 * **Die Sollwerte kommen aus `globals.css`, nicht als Hex im Test.** Der
 * Test liest `--color-text-primary`, `--color-primary` und
 * `--color-primary-soft` zur Laufzeit. Eine Zahl im Test wäre eine
 * zweite Wahrheit und würde beim ersten Nachjustieren am Token falsch
 * (dieselbe Überlegung wie Goldene Regel 13 für Zahlen im Handbuch).
 *
 * Drei Zustände, und alle drei sind Vorgabe:
 *
 * 1. **Ruhe** — Schrift und Symbol tragen das Text-Token, nicht die
 *    Primärfarbe. Beide Knöpfe, weil sie nebeneinanderstehen.
 * 2. **Überfahren** — der Hintergrund wird hell rosé (`primary-soft`,
 *    aus `ghost`), und die Schrift bleibt schwarz. Das zweite ist der
 *    eigentliche Punkt: vorher wurde sie rot.
 * 3. **Gesperrt** — grau über `disabled:opacity-50` aus dem Grundstil.
 *    Die Farbe selbst bleibt das Text-Token; grau entsteht aus der
 *    Deckkraft, und genau so war es vorher auch.
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

/** `erlaubt: false` erzeugt die gesperrte Lage über `temperaturknopf`. */
function raum(erlaubt: boolean): Record<string, unknown> {
  return {
    id: 101,
    number: "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: "occupied",
    // „Dauerhaft gesperrt" ist der Fall, in dem der Knopf grau wird und
    // seinen Grund am umschließenden `span` trägt — `sperreDauerhaft` in
    // `lib/uebersteuerung.ts` hängt an diesem Feld, nicht am Status.
    guest_override_blocked: !erlaubt,
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
}

async function mockApi(page: Page, erlaubt = true): Promise<void> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  // Catch-all zuerst: Playwright trifft die zuletzt registrierte Route
  // zuerst, der Rückhalt steht also oben.
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [RAUMTYP]));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) => json(r, [raum(erlaubt)]));
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

test.describe("Zeilen-Knöpfe: Schrift schwarz", () => {
  test("beide Knöpfe tragen das Text-Token und nicht die Primärfarbe", async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto("/zimmer");

    const schwarz = await token(page, "--color-text-primary");
    const rose = await token(page, "--color-primary");
    // Die Probe hat nur Wert, wenn die beiden Token sich unterscheiden.
    expect(schwarz).not.toBe(rose);

    const temperatur = page.getByRole("button", { name: "Temperatur für Zimmer 101" });
    // „Details" ist `asChild` und damit ein Link, kein Knopf.
    const details = page.getByRole("link", { name: "Details zu Zimmer 101" });

    await expect(temperatur).toBeVisible();
    await expect(details).toBeVisible();
    await expect(temperatur).toHaveCSS("color", schwarz);
    await expect(details).toHaveCSS("color", schwarz);
  });

  test("das Symbol nimmt die Farbe der Schrift", async ({ page }) => {
    // Das Material-Symbol ist eine Schriftart, es erbt `color` — geprüft
    // wird es trotzdem: „Schrift und Icon schwarz" war die Vorgabe, und
    // ein Symbol mit eigener Farbe wäre hier niemandem aufgefallen.
    await mockApi(page);
    await page.goto("/zimmer");

    const schwarz = await token(page, "--color-text-primary");
    const symbol = page
      .getByRole("button", { name: "Temperatur für Zimmer 101" })
      .locator("span.material-symbols-outlined");

    await expect(symbol).toHaveCSS("color", schwarz);
  });

  test("beim Überfahren wird der Hintergrund hell rosé, die Schrift bleibt schwarz", async ({
    page,
  }) => {
    await mockApi(page);
    await page.goto("/zimmer");

    const schwarz = await token(page, "--color-text-primary");
    const soft = await token(page, "--color-primary-soft");
    const knopf = page.getByRole("button", { name: "Temperatur für Zimmer 101" });

    await knopf.hover();
    // `transition-colors` läuft 150 ms; ein sofortiger Vergleich träfe
    // einen Zwischenwert.
    await expect(knopf).toHaveCSS("background-color", soft);
    await expect(knopf).toHaveCSS("color", schwarz);
  });

  test("gesperrt bleibt grau: Text-Token bei halber Deckkraft", async ({ page }) => {
    await mockApi(page, false);
    await page.goto("/zimmer");

    const schwarz = await token(page, "--color-text-primary");
    const knopf = page.getByRole("button", { name: "Temperatur für Zimmer 101" });

    await expect(knopf).toBeDisabled();
    await expect(knopf).toHaveCSS("opacity", "0.5");
    await expect(knopf).toHaveCSS("color", schwarz);
  });
});
