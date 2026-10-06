import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 20f (T6) — der Schicht-Trace sagt, auf welchen Geltungsbereich er
 * sich bezieht.
 *
 * **Der Befund, 05.10.2026.** Die Engine-Ansicht von Zimmer 207 zeigte auf
 * Zimmer-Ebene 21 °C mit „kein aktiver Override" und darunter, im Block
 * „Pro-Zone-Setpoints", Schlafzimmer = 25 °C. Zwei Zahlen, die sich zu
 * widersprechen schienen — und eine Fehlersuche, die davon ausging, dass die
 * Engine zwei verschiedene Sollwerte sendet.
 *
 * Nichts davon war falsch berechnet. Die Zelle zeigt das Ergebnis der
 * **Zimmer**-Abfrage, und die sieht zonen-weite Overrides laut Entwurf nicht
 * (`override_service.get_active` mit `heating_zone_id=None` betrachtet
 * ausschließlich Room-Scope-Overrides). Der Satz war für seinen
 * Geltungsbereich richtig und für den Leser falsch: gelesen wurde „es gibt
 * keinen Override", gemeint war „es gibt keinen **zimmerweiten** Override".
 *
 * Dieselbe Klasse wie §5.57 — die Information ist da, nur nicht dort, wo der
 * Leser sie sucht.
 *
 * Diese Datei baut genau dieses Bild nach: ein Trace mit Room-Scope-Layer
 * ohne Override **und** einem Zonen-Eintrag in der `hard_clamp`-Zeile.
 *
 * Route-Muster sind Regex mit `$` (§5.54), damit sie mit und ohne
 * Query-String greifen.
 */

const MOCK_MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-05T10:00:00Z",
  last_login_at: "2026-10-05T18:00:00Z",
};

const ROOM = {
  id: 207,
  number: "207",
  display_name: null,
  room_type_id: 1,
  floor: 2,
  orientation: null,
  status: "occupied",
  guest_override_blocked: false,
  has_active_override: true,
  notes: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-05T10:00:00Z",
};

const ZONE_SCHLAFZIMMER = {
  id: 244,
  room_id: 207,
  name: "Schlafzimmer",
  kind: "radiator",
  is_towel_warmer: false,
  health_state: "healthy",
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-05T10:00:00Z",
};

/**
 * Trace mit dem Bild vom 05.10.: Zimmer-Ebene **ohne** Override, Zone 244
 * **mit** 25 °C.
 *
 * `details.source = null` in der `manual_override`-Zeile ist genau das, was
 * der Backend-Layer schreibt, wenn der Room-Scope-Lookup nichts findet
 * (`rules/engine.py` `layer_manual_override`, Zweig „no active override").
 */
function traceMitZonenOverride(): unknown[] {
  const evalId = "00000000-0000-0000-0000-00000000020f";
  const now = new Date().toISOString();
  return [
    {
      time: now,
      room_id: 207,
      evaluation_id: evalId,
      layer: "manual_override",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: {
        detail: "no active override",
        source: null,
        expires_at: null,
        override_id: null,
        heating_zone_id: null,
      },
    },
    {
      time: now,
      room_id: 207,
      evaluation_id: evalId,
      layer: "hard_clamp",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "occupied_setpoint",
      details: {
        detail: "within [10,30]",
        zone_overrides_trace: [
          {
            zone_id: 244,
            setpoint_c: 25,
            override_id: 37,
            source: "frontend_midnight",
          },
        ],
      },
    },
  ];
}

/** Derselbe Trace, aber ohne Zonen-Eintrag — der häufige Normalfall. */
function traceOhneZonenOverride(): unknown[] {
  const eintraege = traceMitZonenOverride() as Record<string, unknown>[];
  const clamp = eintraege[1];
  clamp.details = { detail: "within [10,30]" };
  return eintraege;
}

async function mockRaum(page: Page, trace: unknown[]): Promise<void> {
  await page.route("**/api/v1/**", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_MITARBEITER),
    }),
  );
  await page.route(/.*\/api\/v1\/rooms\/207(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ROOM),
    }),
  );
  await page.route(/.*\/api\/v1\/rooms\/207\/heating-zones(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([ZONE_SCHLAFZIMMER]),
    }),
  );
  await page.route(/.*\/api\/v1\/rooms\/207\/engine-trace.*$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(trace),
    }),
  );
}

async function oeffneEngineTab(page: Page): Promise<void> {
  await page.goto("/zimmer/207");
  await page.getByRole("button", { name: "Engine", exact: true }).click();
  await expect(page.getByText("Schicht-Trace")).toBeVisible();
}

test.describe("Sprint 20f — Trace nennt den Geltungsbereich", () => {
  test("Zimmer-Ebene sagt 'kein zimmerweiter Override' und verweist auf den Block", async ({
    page,
  }) => {
    // Das Bild vom 05.10.: Zimmer-Ebene ohne Override, Zone 244 auf 25 °C.
    await mockRaum(page, traceMitZonenOverride());

    await oeffneEngineTab(page);

    // Der alte Text behauptete, es gäbe gar keinen Override.
    await expect(page.getByText("kein aktiver Override")).toHaveCount(0);
    await expect(page.getByText(/kein zimmerweiter Override/)).toBeVisible();
    // Und er sagt, wo der Zonen-Override steht.
    await expect(page.getByText(/siehe/)).toBeVisible();
    await expect(
      page.getByText("Pro-Zone-Setpoints", { exact: true }).first(),
    ).toBeVisible();

    // Der Block selbst ist unverändert da — er war nie das Problem.
    await expect(page.getByText(/Schlafzimmer \(Zone 244\)/)).toBeVisible();
  });

  test("ohne Zonen-Override kein Verweis — der Hinweis bleibt still", async ({
    page,
  }) => {
    // Die Gegenprobe. Ein Verweis auf einen Block, den es nicht gibt, wäre
    // dieselbe Sorte Falschaussage, nur in der anderen Richtung.
    await mockRaum(page, traceOhneZonenOverride());

    await oeffneEngineTab(page);

    await expect(page.getByText(/kein zimmerweiter Override/)).toBeVisible();
    await expect(page.getByText(/siehe/)).toHaveCount(0);
    await expect(page.getByText("Pro-Zone-Setpoints", { exact: true })).toHaveCount(0);
  });
});
