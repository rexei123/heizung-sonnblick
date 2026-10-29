import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 23 T4-A2 — „Gast kann bis Check-out nicht ändern" im
 * Übersteuerungs-Dialog.
 *
 * **Warum es diesen Weg zusätzlich zum Sperr-Knopf gibt.** Der Knopf in
 * der Kopfzeile (T4-A, #340) beginnt die Sperre mit einem Widerruf aller
 * aktiven Übersteuerungen. Für „ab jetzt soll hier niemand mehr drehen"
 * ist das richtig. Für den vereinbarten Fall — die Rezeption setzt
 * **einen bestimmten Wert** und friert ihn ein — ist es das Gegenteil:
 * der Widerruf träfe genau den Wert, den sie gerade eingetragen hat. Das
 * war der Befund des Betreibers, und er ist der Grund für dieses Häkchen.
 *
 * Geprüft wird hier, was man ohne Backend sehen kann:
 *
 * 1. Das Häkchen ist **aus**, und es ist nur mit der Dauer „Bis
 *    Check-out" wählbar — mit einem Satz daneben, der sagt warum. Ein
 *    ausgegrautes Feld ohne Grund erklärt sich der Nutzer selbst, und
 *    zwar falsch (§5.57).
 * 2. Es landet wirklich im Rumpf der Anfrage. Ein Häkchen, das nichts
 *    mitschickt, ist ein Schalter ohne Wirkung (§5.77).
 * 3. Der Wechsel der Dauer **zieht es mit zurück**. Sonst stünde beim
 *    nächsten Wechsel auf „Bis Check-out" eine Absicht da, die niemand
 *    geäußert hat — unsichtbar, weil die Zeile zwischenzeitlich
 *    ausgegraut war.
 * 4. Im Allgemeinbereich gibt es es nicht. Ein Bereich hat keine
 *    Abreise, die Sperre würde dort nie enden; der Server weist sie mit
 *    422 ab, und eine Oberfläche, die anbietet, was der Server abweist,
 *    ist die Fehlerklasse aus Sprint 22.
 * 5. **Die beiden Formen der Sperre sehen verschieden aus.** Die
 *    dauerhafte nimmt das Formular weg (so war es seit Sprint 12c). Die
 *    Sperre „bis Check-out" lässt es stehen — sie nimmt dem Gast das Rad,
 *    nicht der Rezeption die Eingabe.
 */

const MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-29T06:00:00Z",
  last_login_at: "2026-10-29T06:00:00Z",
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

interface RaumLage {
  blocked?: boolean;
  bisCheckout?: boolean;
  bereich?: boolean;
}

function raum(lage: RaumLage = {}): Record<string, unknown> {
  return {
    id: 101,
    number: "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: lage.bereich ? "allgemeinbereich" : "occupied",
    guest_override_blocked: lage.blocked ?? false,
    guest_block_bis_checkout: lage.bisCheckout ?? false,
    ist_allgemeinbereich: lage.bereich ?? false,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-29T06:00:00Z",
  };
}

interface Steuerung {
  /** Der Rumpf des letzten POST auf die Übersteuerungen, oder `null`. */
  gesendet: () => Record<string, unknown> | null;
}

async function mockApi(page: Page, lage: RaumLage = {}): Promise<Steuerung> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  let gesendet: Record<string, unknown> | null = null;

  // Catch-all zuerst registrieren: Playwright trifft die **zuletzt**
  // registrierte Route zuerst, der Rückhalt steht also unten in der
  // Trefferreihenfolge.
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, MITARBEITER));
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (r: Route) =>
    json(r, [ZONE]),
  );
  await page.route(/.*\/api\/v1\/rooms\/101\/engine-trace(\?.*)?$/, (r: Route) => json(r, []));
  // Muss VOR `/rooms/101` stehen (zuletzt registriert trifft zuerst).
  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (r: Route) => {
    if (r.request().method() === "POST") {
      gesendet = JSON.parse(r.request().postData() ?? "{}") as Record<string, unknown>;
      await r.fulfill({ status: 201, contentType: "application/json", body: "{}" });
      return;
    }
    await json(r, []);
  });
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (r: Route) => json(r, raum(lage)));

  return { gesendet: () => gesendet };
}

/** Zimmerseite öffnen und auf den Reiter „Übersteuerung" wechseln. */
async function zumReiter(page: Page): Promise<void> {
  await page.goto("/zimmer/101");
  await page.getByRole("button", { name: "Übersteuerung", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Schlafzimmer" })).toBeVisible();
}

/** Die Dauer im Auswahlfeld der Zone setzen. */
async function waehleDauer(page: Page, label: RegExp): Promise<void> {
  await page.getByRole("combobox").first().click();
  await page.getByRole("option", { name: label }).click();
}

test.describe("Sprint 23 T4-A2 Gast-Sperre im Dialog", () => {
  test("das Häkchen ist aus und bei 24 Stunden nicht wählbar", async ({ page }) => {
    await mockApi(page);
    await zumReiter(page);

    const haken = page.getByTestId("gast-sperre-haken");
    await expect(haken).toBeVisible();
    await expect(haken).not.toBeChecked();
    // Die Vorauswahl der Dauer ist „24 Stunden" — hier also gesperrt.
    await expect(haken).toBeDisabled();
    await expect(page.getByTestId("gast-sperre-hinweis")).toContainText(
      /Nur mit der Dauer/,
    );
  });

  test("mit Bis Check-out wird es wählbar und der Satz wechselt", async ({ page }) => {
    await mockApi(page);
    await zumReiter(page);

    await waehleDauer(page, /Bis Check-out/);

    await expect(page.getByTestId("gast-sperre-haken")).toBeEnabled();
    // Der Satz nennt jetzt die Wirkung, nicht die Bedingung: dass das
    // Personal weiter ändern kann, ist die Information, die an der
    // Rezeption gebraucht wird.
    await expect(page.getByTestId("gast-sperre-hinweis")).toContainText(
      /Rezeption kann weiter ändern/,
    );
  });

  test("das Häkchen landet im Rumpf der Anfrage", async ({ page }) => {
    const ctrl = await mockApi(page);
    await zumReiter(page);

    await waehleDauer(page, /Bis Check-out/);
    await page.getByTestId("gast-sperre-haken").check();
    await page.getByRole("button", { name: "Anwenden" }).click();

    await expect.poll(() => ctrl.gesendet()).toMatchObject({
      setpoint: "21",
      source: "frontend_checkout",
      gast_sperre_bis_checkout: true,
      heating_zone_id: 201,
    });
  });

  test("ohne Häkchen fährt das Feld nicht mit", async ({ page }) => {
    // Der Standard ist AUS, und „aus" heißt hier: das Feld fehlt im
    // Rumpf. Ein `false`, das mitfährt, wäre nicht falsch — aber es
    // würde behaupten, jemand habe sich entschieden.
    const ctrl = await mockApi(page);
    await zumReiter(page);

    await waehleDauer(page, /Bis Check-out/);
    await page.getByRole("button", { name: "Anwenden" }).click();

    await expect.poll(() => ctrl.gesendet()).not.toBeNull();
    expect(ctrl.gesendet()).not.toHaveProperty("gast_sperre_bis_checkout");
  });

  test("der Wechsel der Dauer zieht das Häkchen mit zurück", async ({ page }) => {
    const ctrl = await mockApi(page);
    await zumReiter(page);

    await waehleDauer(page, /Bis Check-out/);
    await page.getByTestId("gast-sperre-haken").check();
    await expect(page.getByTestId("gast-sperre-haken")).toBeChecked();

    // Zurück auf 24 Stunden: der Haken muss fallen, nicht nur ausgrauen.
    await waehleDauer(page, /24 Stunden/);
    await expect(page.getByTestId("gast-sperre-haken")).not.toBeChecked();

    // Und er darf auch nicht heimlich mitfahren.
    await page.getByRole("button", { name: "Anwenden" }).click();
    await expect.poll(() => ctrl.gesendet()).not.toBeNull();
    expect(ctrl.gesendet()).not.toHaveProperty("gast_sperre_bis_checkout");
  });

  test("im Allgemeinbereich gibt es das Häkchen nicht", async ({ page }) => {
    await mockApi(page, { bereich: true });
    await zumReiter(page);

    // Das Formular des Bereichs steht (Dauer in Minuten, Sprint 24d) …
    await expect(page.getByTestId("bereich-dauer")).toBeVisible();
    // … und das Häkchen nicht.
    await expect(page.getByTestId("gast-sperre-haken")).toHaveCount(0);
  });

  test("die Sperre bis Check-out lässt das Formular stehen", async ({ page }) => {
    await mockApi(page, { blocked: true, bisCheckout: true });
    await zumReiter(page);

    await expect(page.getByTestId("sperre-banner")).toContainText(
      "Gast kann bis Check-out nicht ändern",
    );
    await expect(page.getByTestId("sperre-banner")).toContainText(
      /Rezeption kann den Wert weiter ändern/,
    );
    // Der eigentliche Punkt: die Rezeption kann weiter eintragen.
    await expect(page.getByRole("button", { name: "Anwenden" })).toBeVisible();
  });

  test("die dauerhafte Sperre nimmt das Formular weg", async ({ page }) => {
    // Regression auf Sprint 12c: an dieser Form ändert T4-A2 nichts.
    await mockApi(page, { blocked: true, bisCheckout: false });
    await zumReiter(page);

    await expect(page.getByTestId("sperre-banner")).toContainText("Übersteuerung gesperrt");
    await expect(page.getByRole("button", { name: "Anwenden" })).toHaveCount(0);
    await expect(page.getByTestId("gast-sperre-haken")).toHaveCount(0);
  });
});
