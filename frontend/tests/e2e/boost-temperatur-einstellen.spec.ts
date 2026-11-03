import { expect, test, type Page, type Route } from "./fixtures";

/**
 * „Boost" als vierte Zeile unter Globale Temperaturen (02.11.2026).
 *
 * Festlegung des Betreibers vom 31.10.2026: die Boost-Temperatur soll in
 * den globalen Temperatur-Einstellungen änderbar sein — dieselbe
 * Darstellung wie „Zimmer belegt", „Zimmer frei" und „Nachtabsenkung".
 *
 * Geprüft wird, was man ohne Backend sehen kann:
 *
 * 1. **Die Zeile ist da**, mit dem Hinweistext und dem Wert in °C.
 * 2. **Der Bereich 18–25 greift schon im Browser** — die Zod-Prüfung in
 *    der Zelle, damit eine falsche Eingabe nicht erst als 422
 *    zurückkommt. Das Backend prüft denselben Bereich noch einmal
 *    (`test_api_rule_configs::test_boost_temperatur_hat_ihren_eigenen_bereich`);
 *    die Zelle ist Bedienung, nicht Schutz (§5.30).
 * 3. **Beide Rollen, ausdrücklich gesetzt** und nicht über den Standard
 *    der Hülle (Bedingung des Betreibers vom 14.10.2026): ein
 *    Administrator darf ändern, ein Mitarbeiter sieht den Wert und kann
 *    ihn nicht anfassen — genau wie bei den drei Zeilen darüber, weil
 *    `PATCH /rule-configs/global` `require_admin` ist.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-11-02T08:00:00Z",
  last_login_at: "2026-11-02T08:00:00Z",
};

const MITARBEITER = {
  ...ADMIN,
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
};

const INITIAL = {
  id: 1,
  t_occupied: "21.0",
  t_vacant: "18.0",
  t_night: "19.0",
  boost_temperature: "23.0",
  night_start: "00:00:00",
  night_end: "06:00:00",
  preheat_minutes_before_checkin: 90,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-02T08:00:00Z",
};

interface Steuerung {
  /** Der Rumpf des letzten PATCH, oder `null`. */
  gesendet: () => Record<string, unknown> | null;
}

async function mockApi(
  page: Page,
  rolle: typeof ADMIN | typeof MITARBEITER = ADMIN,
): Promise<Steuerung> {
  let stand: Record<string, unknown> = { ...INITIAL };
  let gesendet: Record<string, unknown> | null = null;

  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(rolle),
    }),
  );
  // Zwei Nebenanfragen der Seite, die dieser Test nicht prüft.
  await page.route(/.*\/api\/v1\/rule-configs\/global\/nutzung(\?.*)?$/, (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/scenarios(\?.*)?$/, (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/rule-configs\/global(\?.*)?$/, async (r: Route) => {
    if (r.request().method() === "PATCH") {
      gesendet = r.request().postDataJSON() as Record<string, unknown>;
      stand = { ...stand, ...gesendet, updated_at: new Date().toISOString() };
      await r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(stand),
      });
      return;
    }
    await r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stand),
    });
  });

  return { gesendet: () => gesendet };
}

async function zumTemperaturTab(page: Page): Promise<void> {
  await page.goto("/einstellungen/temperaturen-zeiten");
  await page.getByRole("tab", { name: "Globale Temperaturen" }).click();
}

test.describe("Boost-Temperatur unter Globale Temperaturen", () => {
  test("die Zeile steht da, mit Hinweis und Wert", async ({ page }) => {
    await mockApi(page);
    await zumTemperaturTab(page);

    const knopf = page.getByRole("button", { name: "Boost bearbeiten" });
    await expect(knopf).toContainText("23.0 °C");
    // Der Hinweistext ist der des Betreibers — er sagt, was der Wert
    // bedeutet **und** wann er endet.
    await expect(
      page.getByText(/Zieltemperatur für Boost; endet mit der nächsten Nachtabsenkung/),
    ).toBeVisible();
  });

  test("sie steht unter den drei anderen und nicht dazwischen", async ({ page }) => {
    // Die Reihenfolge ist die Festlegung („vierte Zeile"). Ein Wert, der
    // zwischen „Zimmer frei" und „Nachtabsenkung" rutscht, ist nicht
    // falsch, aber nicht das, was abgesprochen war.
    await mockApi(page);
    await zumTemperaturTab(page);

    const zeilen = await page
      .getByRole("button", { name: /bearbeiten$/ })
      .evaluateAll((el) => el.map((e) => e.getAttribute("aria-label")));

    expect(zeilen).toEqual([
      "Zimmer belegt bearbeiten",
      "Zimmer frei bearbeiten",
      "Nachtabsenkung bearbeiten",
      "Boost bearbeiten",
    ]);
  });

  test("der Bereich 18–25 greift schon im Browser", async ({ page }) => {
    const ctrl = await mockApi(page);
    await zumTemperaturTab(page);

    await page.getByRole("button", { name: "Boost bearbeiten" }).click();
    const feld = page.getByRole("textbox", { name: "Boost" });

    // Beide Grenzen, beide knapp daneben. Ein Test, der nur 40 probiert,
    // besteht auch mit einem falschen Bereich.
    for (const falsch of ["17.9", "25.1"]) {
      await feld.fill(falsch);
      await page.keyboard.press("Enter");
      await expect(page.getByRole("alert").first()).toContainText("Bereich 18.0–25.0 °C");
      await expect(feld).toBeVisible();
    }

    expect(ctrl.gesendet()).toBeNull();
  });

  test("ein Administrator ändert den Wert, und er kommt als Dezimalzahl", async ({
    page,
  }) => {
    const ctrl = await mockApi(page, ADMIN);
    await zumTemperaturTab(page);

    await page.getByRole("button", { name: "Boost bearbeiten" }).click();
    await page.getByRole("textbox", { name: "Boost" }).fill("24.5");
    await page.keyboard.press("Enter");

    await expect(page.getByText("Gespeichert — Engine übernimmt in ≤ 60 s")).toBeVisible();
    // Als **String** im Rumpf, nicht als Zahl: eine Dezimalzahl, die
    // durch ein JSON-Float läuft, kommt als 24.499999 zurück.
    await expect.poll(() => ctrl.gesendet()).toEqual({ boost_temperature: "24.5" });
    await expect(page.getByRole("button", { name: "Boost bearbeiten" })).toContainText(
      "24.5 °C",
    );
  });

  test("ein Mitarbeiter sieht den Wert und kann ihn nicht ändern", async ({ page }) => {
    // `PATCH /rule-configs/global` ist `require_admin` — wer nicht darf,
    // soll die Zelle nicht öffnen können, statt sie zu öffnen und 403 zu
    // bekommen. Dieselbe Regel wie bei den drei Zeilen darüber.
    await mockApi(page, MITARBEITER);
    await zumTemperaturTab(page);

    await expect(page.getByText("23.0 °C")).toBeVisible();
    await expect(page.getByRole("button", { name: "Boost bearbeiten" })).toHaveCount(0);
  });
});
