import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Zimmerübersicht: Spalten „Ist" und „Soll" (15.10.2026).
 *
 * Geprüft werden die drei Zusagen, die in der Oberfläche liegen:
 *
 * 1. Beide Spalten sind da und zeigen die Werte der **Referenzzone** —
 *    welche das ist, entscheidet das Backend, hier kommt sie fertig an.
 * 2. **Hervorhebung** bei mehr als 2 °C unter Soll, über ein
 *    Design-Token (`text-info`) und nicht über einen Inline-Style.
 * 3. **Fehlender Wert → „–"**, und zwar ohne Fehler: kein Gerät, kein
 *    Messwert und kein Schlafzimmer sehen in der Zeile gleich aus.
 *
 * Die Grenze selbst wird an drei Zeilen gefahren: deutlich darunter
 * (hervorgehoben), **genau** 2,0 K (nicht hervorgehoben — „mehr als")
 * und wärmer als Soll (nicht hervorgehoben).
 *
 * Rolle: der Standard-Admin aus `fixtures.ts`. Die Spalten sind für alle
 * Rollen sichtbar und nur lesend, deshalb prüft der letzte Test
 * ausdrücklich `mitarbeiter` — dort darf nichts fehlen.
 */

interface ZeilenWerte {
  number: string;
  reference_zone_id: number | null;
  mean_temperature_c: number | null;
  engine_setpoint_c: number | null;
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

function roomMock(i: number, w: ZeilenWerte): Record<string, unknown> {
  return {
    id: 500 + i,
    number: w.number,
    display_name: null,
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: "occupied",
    guest_override_blocked: false,
    notes: null,
    has_active_override: false,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-15T06:00:00Z",
    reference_zone_id: w.reference_zone_id,
    mean_temperature_c: w.mean_temperature_c,
    engine_setpoint_c: w.engine_setpoint_c,
  };
}

async function mockApi(
  page: Page,
  zeilen: ZeilenWerte[],
  rolle: "admin" | "mitarbeiter" = "admin",
): Promise<void> {
  const json = (route: Route, body: unknown) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  // Catch-all zuerst: Playwright trifft die zuletzt registrierte Route.
  await page.route("**/api/v1/**", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    json(r, {
      id: 1,
      email: "chef@hotel.example.com",
      role: rolle,
      is_active: true,
      must_change_password: false,
      created_at: "2026-05-01T10:00:00Z",
      updated_at: "2026-10-15T06:00:00Z",
      last_login_at: "2026-10-15T06:00:00Z",
    }),
  );
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [RAUMTYP]));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) =>
    json(
      r,
      zeilen.map((w, i) => roomMock(i, w)),
    ),
  );
}

const WERTE: ZeilenWerte[] = [
  // deutlich zu kalt: 2,5 K unter Soll -> hervorgehoben
  { number: "101", reference_zone_id: 11, mean_temperature_c: 19.5, engine_setpoint_c: 22 },
  // genau 2,0 K darunter -> NICHT hervorgehoben („mehr als 2 °C")
  { number: "102", reference_zone_id: 12, mean_temperature_c: 20, engine_setpoint_c: 22 },
  // waermer als Soll -> nicht hervorgehoben
  { number: "103", reference_zone_id: 13, mean_temperature_c: 23.4, engine_setpoint_c: 21 },
  // kein Messwert (Geraet stumm) -> „–"
  { number: "104", reference_zone_id: 14, mean_temperature_c: null, engine_setpoint_c: 21 },
  // kein Schlafzimmer -> keine Referenzzone, kein Ist
  { number: "105", reference_zone_id: null, mean_temperature_c: null, engine_setpoint_c: 20 },
  // Engine hat seit ueber einer Stunde nichts geschrieben -> Soll „–"
  { number: "106", reference_zone_id: 16, mean_temperature_c: 18, engine_setpoint_c: null },
];

test.describe("Zimmerübersicht — Ist und Soll", () => {
  test("beide_spalten_mit_werten_der_referenzzone", async ({ page }) => {
    await mockApi(page, WERTE);
    await page.goto("/zimmer");

    // **Nicht** `getByRole("columnheader")`: in dieser Tabelle tragen die
    // `<th>` kein `scope`, und Chromium stellt sie deshalb als `cell` in den
    // Baum — gemessen am 15.10.2026, 16 Zellen als `cell`, 0 als
    // `columnheader`, bei Rollen `table` und `row` vorhanden. Mit
    // `scope="col"` waere die Rolle da (und Screenreader nennten die Spalte
    // je Zelle); das ist ein eigener kleiner Zug fuer alle acht Kopfzellen,
    // nicht Teil dieser Spalten.
    const kopf = page.locator("thead th");
    await expect(kopf.filter({ hasText: /^Ist$/ })).toBeVisible();
    await expect(kopf.filter({ hasText: /^Soll$/ })).toBeVisible();
    await expect(kopf).toHaveCount(8);

    await expect(page.getByTestId("ist-101")).toHaveText("19.5 °C");
    await expect(page.getByTestId("soll-101")).toHaveText("22.0 °C");
    await expect(page.getByTestId("ist-103")).toHaveText("23.4 °C");
    await expect(page.getByTestId("soll-103")).toHaveText("21.0 °C");
  });

  test("hervorhebung_nur_bei_mehr_als_zwei_grad_darunter", async ({ page }) => {
    await mockApi(page, WERTE);
    await page.goto("/zimmer");

    // 2,5 K darunter: hervorgehoben, und zwar über das Token — nicht über
    // einen Inline-Style (der Test prüft beides, weil „farbig" sonst auch
    // mit `style="color:…"` erfüllt wäre).
    const kalt = page.getByTestId("ist-101");
    await expect(kalt).toHaveClass(/text-info/);
    await expect(kalt).not.toHaveAttribute("style", /color/);

    // Genau 2,0 K: grau. Das ist die Grenze selbst, nicht ihre Umgebung.
    await expect(page.getByTestId("ist-102")).not.toHaveClass(/text-info/);
    await expect(page.getByTestId("ist-102")).toHaveClass(/text-text-secondary/);

    // Wärmer als Soll: grau.
    await expect(page.getByTestId("ist-103")).not.toHaveClass(/text-info/);
  });

  test("fehlender_wert_zeigt_strich_und_keinen_fehler", async ({ page }) => {
    const konsole: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") konsole.push(m.text());
    });

    await mockApi(page, WERTE);
    await page.goto("/zimmer");

    // Kein Messwert, keine Referenzzone, kein Soll — dreimal „–".
    await expect(page.getByTestId("ist-104")).toHaveText("–");
    await expect(page.getByTestId("ist-105")).toHaveText("–");
    await expect(page.getByTestId("soll-106")).toHaveText("–");

    // Der Soll steht trotzdem, wo es ihn gibt: er hängt am Zimmer, nicht
    // an der Zone.
    await expect(page.getByTestId("soll-104")).toHaveText("21.0 °C");
    await expect(page.getByTestId("soll-105")).toHaveText("20.0 °C");

    // Und ein fehlender Wert ist kein Fehler.
    await expect(page.getByTestId("ist-106")).toHaveText("18.0 °C");
    expect(konsole).toEqual([]);
  });

  test("mitarbeiter_sieht_beide_spalten", async ({ page }) => {
    await mockApi(page, WERTE, "mitarbeiter");
    await page.goto("/zimmer");

    // Anker: die Rolle ist geladen (sonst prüfte der Test den Zustand vor
    // der `/auth/me`-Antwort).
    await expect(page.getByText("Mitarbeiter", { exact: true })).toBeVisible();

    await expect(page.getByTestId("ist-101")).toHaveText("19.5 °C");
    await expect(page.getByTestId("soll-101")).toHaveText("22.0 °C");
    await expect(page.getByTestId("ist-101")).toHaveClass(/text-info/);

    // Nur lesend: die Spalten tragen keine Schaltfläche.
    await expect(page.getByTestId("ist-101").getByRole("button")).toHaveCount(0);
    await expect(page.getByTestId("soll-101").getByRole("button")).toHaveCount(0);
  });
});
