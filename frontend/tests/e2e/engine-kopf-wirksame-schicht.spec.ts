import { expect, test, type Page, type Route } from "./fixtures";

/**
 * Der Kopf der Engine-Seite nennt die Schicht, die den Wert gesetzt hat
 * (03.11.2026).
 *
 * **Der Anlass ist die Boost-Abnahme §10ax.** Bei laufendem Boost stand
 * dort „23°C · Grund: Frei-Sollwert · Sollwert aus: hausweit" — die Zahl
 * aus `hard_clamp` (Ende der Kette), der Grund aus `base_target`
 * (Anfang). Beide Hälften waren für sich richtig und zusammen falsch.
 *
 * **Der Fehler war nicht boost-eigen.** Jede Übersteuerung erzeugte ihn.
 * Zwei dieser Tests prüfen deshalb nicht den Boost: einer die gewöhnliche
 * Wunschtemperatur, einer den Fall, in dem eine **spätere** Schicht den
 * Wert noch einmal ändert — dann gehört der Kopf ihr und nicht der
 * Übersteuerung.
 *
 * **Und einer prüft, dass der gute Fall unverändert ist.** Ohne
 * Übersteuerung ist die Basis-Schicht die wirksame, und „Sollwert aus"
 * muss weiter dastehen. Ein Fix, der den Normalfall mitnimmt, wäre kein
 * Fix.
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
  id: 52,
  number: "52",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "vacant",
  guest_override_blocked: false,
  guest_block_bis_checkout: false,
  ist_allgemeinbereich: false,
  has_active_override: false,
  uebersteuerung_quelle: null,
  uebersteuerung_ende: null,
  boost_moeglich: true,
  boost_grund: null,
  boost_hinweis: null,
  boost_ende: "2026-11-03T19:00:00Z",
  notes: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-11-03T06:00:00Z",
  reference_zone_id: 201,
  mean_temperature_c: 18.2,
  engine_setpoint_c: 23,
};

const ZONE = {
  id: 201,
  room_id: 52,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

/**
 * Das Ende des Boosts, wie es in der Abnahme stand: **20:00 Ortszeit**.
 * Im November ist Wien UTC+1, also 19:00 UTC — der Test schreibt UTC in
 * die Antwort und erwartet Ortszeit in der Anzeige. Genau diese
 * Umrechnung ist die Stelle, an der eine Endzeit sonst um eine Stunde
 * verrutscht (§5.65).
 */
const BOOST_ENDE_UTC = "2026-11-03T19:00:00Z";
const BOOST_ENDE_ORTSZEIT = "20:00";

const EVAL_ID = "00000000-0000-0000-0000-00000000ax01";

interface Schicht {
  layer: string;
  setpoint_in: string | null;
  setpoint_out: string | null;
  reason: string | null;
  details: Record<string, unknown> | null;
}

function trace(schichten: Schicht[]): unknown[] {
  const now = new Date().toISOString();
  return schichten.map((s) => ({
    time: now,
    room_id: ROOM.id,
    evaluation_id: EVAL_ID,
    device_id: null,
    ...s,
  }));
}

/** Basis: freies Zimmer, 15 °C aus der hausweiten Zeile. */
const BASIS: Schicht = {
  layer: "base_target",
  setpoint_in: "15.0",
  setpoint_out: "15.0",
  reason: "vacant_setpoint",
  details: { detail: "status=vacant", sollwert_quelle: "global" },
};

/** Eine Übersteuerung, die den Wert anhebt. */
function uebersteuerung(source: string, bis: string | null, auf: string): Schicht {
  return {
    layer: "manual_override",
    setpoint_in: "15.0",
    setpoint_out: auf,
    reason: "manual",
    details: { detail: `override source=${source}`, source, expires_at: bis },
  };
}

/** Das Ende der Kette, ohne eigene Wirkung. */
function clamp(wert: string, grund: string): Schicht {
  return {
    layer: "hard_clamp",
    setpoint_in: wert,
    setpoint_out: wert,
    reason: grund,
    details: { detail: "within [15,25]" },
  };
}

async function mockApi(page: Page, schichten: Schicht[]): Promise<void> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  // Catch-all zuerst: Playwright trifft die zuletzt registrierte Route
  // zuerst, der Rückhalt steht also oben.
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/rooms\/52(\?.*)?$/, (r: Route) => json(r, ROOM));
  await page.route(/.*\/api\/v1\/rooms\/52\/heating-zones(\?.*)?$/, (r: Route) =>
    json(r, [ZONE]),
  );
  await page.route(/.*\/api\/v1\/rooms\/52\/engine-trace(\?.*)?$/, (r: Route) =>
    json(r, trace(schichten)),
  );
}

async function zumEngineReiter(page: Page): Promise<void> {
  await page.goto("/zimmer/52");
  await page.getByRole("button", { name: "Engine", exact: true }).click();
}

test.describe("Engine-Kopf: die wirksame Schicht", () => {
  test("laufender Boost: Etikett und Endzeit, und keine erfundene Herkunft", async ({
    page,
  }) => {
    await mockApi(page, [
      BASIS,
      uebersteuerung("frontend_boost", BOOST_ENDE_UTC, "23.0"),
      clamp("23.0", "manual"),
    ]);
    await zumEngineReiter(page);

    // Die Zahl **des Kopfes**, nicht die im Trace darunter — dass beide
    // dieselbe ist, war nie das Problem.
    await expect(page.getByTestId("trace-sollwert")).toHaveText("23°C");
    await expect(page.getByTestId("trace-grund")).toHaveText(
      `Boost (Mitarbeiter) bis ${BOOST_ENDE_ORTSZEIT}`,
    );
    // **Der zweite Teil des Fehlers.** „Sollwert aus: hausweit" war eine
    // Herkunft für einen Wert, der nicht von dort kam — der Boost bringt
    // seinen eigenen mit. Die Zeile muss deshalb ganz fehlen.
    await expect(page.getByTestId("trace-quelle")).toHaveCount(0);
  });

  test("eine gewöhnliche Wunschtemperatur genauso — der Fehler war nicht boost-eigen", async ({
    page,
  }) => {
    await mockApi(page, [
      BASIS,
      uebersteuerung("frontend_24h", "2026-11-04T07:00:00Z", "21.0"),
      clamp("21.0", "manual"),
    ]);
    await zumEngineReiter(page);

    await expect(page.getByTestId("trace-grund")).toHaveText(
      "24 Stunden (Mitarbeiter) bis 08:00",
    );
    await expect(page.getByTestId("trace-quelle")).toHaveCount(0);
  });

  test("ändert eine spätere Schicht den Wert, gehört der Kopf ihr", async ({ page }) => {
    // Fenster offen **nach** der Übersteuerung: der Wert kommt von der
    // Fenster-Schicht, also auch der Grund. Ein Fix, der „irgendeine
    // Übersteuerung gewinnt" baut, besteht diesen Test nicht.
    await mockApi(page, [
      BASIS,
      uebersteuerung("frontend_boost", BOOST_ENDE_UTC, "23.0"),
      {
        layer: "window_safety",
        setpoint_in: "23.0",
        setpoint_out: "8.0",
        reason: "window_open",
        details: { detail: "open_zone=201" },
      },
      clamp("8.0", "window_open"),
    ]);
    await zumEngineReiter(page);

    await expect(page.getByTestId("trace-grund")).toHaveText("Fenster offen");
    await expect(page.getByTestId("trace-quelle")).toHaveCount(0);
  });

  test("ohne Übersteuerung bleibt alles, wie es war", async ({ page }) => {
    // Der Normalfall: die Basis-Schicht ist die wirksame, und „Sollwert
    // aus" sagt weiter, aus welcher Zeile der Wert kommt.
    await mockApi(page, [BASIS, clamp("15.0", "vacant_setpoint")]);
    await zumEngineReiter(page);

    await expect(page.getByTestId("trace-grund")).toHaveText("Frei-Sollwert");
    await expect(page.getByTestId("trace-quelle")).toContainText("hausweit");
  });
});
