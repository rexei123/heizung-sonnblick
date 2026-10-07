import { test, expect } from "@playwright/test";

/**
 * Sprint 17 (C9) — HardwareStatusBadge unterscheidet drei Zustände.
 *
 * Bis Sprint 16 zeigte der Badge "Aktiv" / "Inaktiv" mit der Unterzeile
 * "Zuletzt: …" bzw. "noch nie". Das liest sich wie ein Online-Status,
 * gemessen wird aber die Montage: der Endpoint aggregiert
 * `sensor_reading.attached_backplate` der letzten 30 Minuten.
 *
 * Folge am Tisch (vor der Montage): `attached_backplate=false` ist dort der
 * *erwartete* Zustand, und jedes gesunde Gerät stand als
 * "Inaktiv — noch nie" da, während daneben "Batterie OK" stand.
 *
 * Die drei Zustände kommen aus denselben Antwortfeldern — kein Backend-
 * und kein Type-Change:
 *
 *   frames_in_window = 0        -> "Keine Daten (30 Min)"
 *   frames > 0, kein TRUE-Frame -> "Nicht montiert"
 *   TRUE-Frame im Fenster       -> "Montiert"
 */

const DEVICE_ID = 42;

const SAMPLE_DEVICE = {
  id: DEVICE_ID,
  dev_eui: "0011223344556677",
  app_eui: null,
  kind: "thermostat",
  vendor: "mclimate",
  model: "Vicki",
  label: "101",
  heating_zone_id: 7,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
  updated_at: new Date().toISOString(),
  firmware_version: "4.2",
  health_state: "healthy",
  hardware_number: "MDC5419731K6UF",
  heating_zone: {
    id: 7,
    name: "Schlafbereich",
    health_state: "healthy",
    room: { id: 1, number: "101", room_type: { id: 1, name: "Doppelzimmer" } },
  },
  active_override: null,
  latest_reading: null,
  valve_state: "ok" as const,
  valve_delta_k: null,
  battery_state: "ok",
};

/**
 * Dasselbe Gerät ohne Zuordnung — Reserve-Pool (Sprint 20).
 * ``heating_zone_id === null`` ist die Quelle des ``isPool``-Props.
 */
const POOL_DEVICE = {
  ...SAMPLE_DEVICE,
  heating_zone_id: null,
  heating_zone: null,
};

/** Antwort des hardware-status-Endpoints für den jeweiligen Zustand. */
const HW = {
  montiert: {
    status: "active",
    last_seen: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
    source: "window" as const,
    mounted_confirmed_at: null,
    frames_in_window: 3,
    window_minutes: 30,
  },
  nichtMontiert: {
    // Frames kommen an, aber keiner meldet attached_backplate=true.
    status: "inactive",
    last_seen: null,
    source: "window" as const,
    mounted_confirmed_at: null,
    frames_in_window: 3,
    window_minutes: 30,
  },
  keineDaten: {
    // Gar kein Frame mit dem Feld: alter Codec, FW < 4.1 oder kein Uplink.
    status: "inactive",
    last_seen: null,
    source: "window" as const,
    mounted_confirmed_at: null,
    frames_in_window: 0,
    window_minutes: 30,
  },
};

type HwStatus = (typeof HW)[keyof typeof HW];

/**
 * Registriert die Mocks für die Geräte-Detailseite (detailed-Variante).
 *
 * §5.54: Regex statt Glob, weil die Folge-URLs Query-Strings tragen
 * (`?limit=…`) und Globs darüber nicht zuverlässig matchen.
 */
async function mockDetailPage(
  page: import("@playwright/test").Page,
  hw: HwStatus,
  device: unknown = SAMPLE_DEVICE,
) {
  await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(hw),
    }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+\/sensor-readings(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(device),
    }),
  );
}

test.describe("Sprint 17 C9 / Sprint 20 — vier Montage-Zustände", () => {
  test("TRUE-Frame im Fenster -> Montiert, mit Zeitangabe", async ({ page }) => {
    await mockDetailPage(page, HW.montiert);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Montiert");
    await expect(badge).toContainText(/Montiert zuletzt:/);
    // Nicht der Nachbarzustand.
    await expect(badge).not.toContainText("Nicht montiert");
    await expect(badge).not.toContainText("Keine Daten");
  });

  test("Frames da, aber keiner meldet montiert -> Nicht montiert", async ({ page }) => {
    await mockDetailPage(page, HW.nichtMontiert);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Nicht montiert");
    // Sprint 20: „noch nicht gemeldet" war hier falsch — das Geraet meldet
    // sich (frames_in_window = 3), nur kein Frame sagt „montiert".
    await expect(badge).toContainText("meldet sich, nicht montiert");
    await expect(badge).not.toContainText("noch nicht gemeldet");
    await expect(badge).not.toContainText("Keine Daten");
  });

  test("Sprint 20: Pool-Geraet, das sich meldet -> Im Lager, grau", async ({ page }) => {
    // Derselbe Endpoint-Zustand wie im Test darueber (Frames da, kein
    // True-Frame) — nur ohne Zuordnung. Bis Sprint 19 stand hier rot
    // „Nicht montiert / noch nicht gemeldet": zwei Fehlaussagen in einer
    // Zeile, obwohl das Geraet genau das tut, was es im Lager tun soll.
    await mockDetailPage(page, HW.nichtMontiert, POOL_DEVICE);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    const pille = badge.locator("span").first();
    await expect(pille).toContainText("Im Lager");
    await expect(badge).toContainText("meldet sich, nicht montiert");
    // Neutral, nicht rot: die Farbe ist die eigentliche Aussage. Geprueft an
    // der Pille, nicht am Text — „nicht montiert" steht in der Unterzeile
    // weiter und ist dort richtig.
    await expect(pille).not.toHaveClass(/text-danger/);
  });

  test("Sprint 20: montiertes Pool-Geraet bleibt Montiert (Zustand im Eingangstest)", async ({
    page,
  }) => {
    // Die Montage-Reihenfolge aus RUNBOOK §10h.6 fuehrt durch genau diesen
    // Zustand: montieren -> Eingangstest, Geraet noch Pool -> assign. Waere
    // „Im Lager" an die Zuordnung allein gekoppelt, stuende hier das Falsche.
    await mockDetailPage(page, HW.montiert, POOL_DEVICE);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Montiert");
    await expect(badge).not.toContainText("Im Lager");
  });

  test("kein verwertbarer Frame -> Keine Daten (30 Min)", async ({ page }) => {
    await mockDetailPage(page, HW.keineDaten);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Keine Daten (30 Min)");
    await expect(badge).toContainText("noch nicht gemeldet");
    // Das ist ausdruecklich NICHT "Nicht montiert" — der Unterschied ist der
    // Punkt dieses Sprints.
    await expect(badge).not.toContainText("Nicht montiert");
  });

  test("compact-Variante zeigt dieselben Zustände, Unterzeile im Tooltip", async ({
    page,
  }) => {
    // /zimmer/[id] rendert die compact-Variante im Geraete-Tab.
    await page.route(/.*\/api\/v1\/.*/, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([SAMPLE_DEVICE]),
      }),
    );
    await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(HW.nichtMontiert),
      }),
    );
    await page.route(/.*\/api\/v1\/rooms\/1\/heating-zones(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: 7,
            room_id: 1,
            kind: "bedroom",
            name: "Schlafbereich",
            is_towel_warmer: false,
            created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
            updated_at: new Date().toISOString(),
          },
        ]),
      }),
    );
    await page.route(/.*\/api\/v1\/rooms\/1(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 1,
          number: "101",
          display_name: null,
          room_type_id: 1,
          floor: 1,
          orientation: "S",
          status: "vacant",
          notes: null,
          created_at: new Date(Date.now() - 86400 * 1000).toISOString(),
          updated_at: new Date().toISOString(),
        }),
      }),
    );

    await page.goto("/zimmer/1");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Nicht montiert");
    // compact traegt die Unterzeile als Tooltip, nicht als sichtbaren Text.
    // Sprint 20: die Zeile sagt jetzt, was zutrifft — das Geraet meldet sich.
    await expect(badge).toHaveAttribute("title", "meldet sich, nicht montiert");
  });
});
