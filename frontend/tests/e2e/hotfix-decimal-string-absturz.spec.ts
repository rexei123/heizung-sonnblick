import { test, expect } from "@playwright/test";

/**
 * Der Absturz vom 07.10.2026, als Test — mit der **echten** Serialisierung.
 *
 * `/devices` war nach dem Deploy von Sprint 20e nicht mehr benutzbar:
 *
 *     Application error: a client-side exception
 *     TypeError: a.toFixed is not a function
 *
 * `DeviceRead.valve_delta_k` ist im Backend ein `Decimal` und stand nicht im
 * `field_serializer`. Pydantic serialisiert ein `Decimal` ohne Eintrag als
 * JSON-**String** (`"5.40"`), der TypeScript-Typ sagt aber `number | null`,
 * und `formatDelta` rief `.toFixed()` darauf.
 *
 * **Warum die e2e-Tests grün waren.** Ihre Mocks trugen Zahlen — also meine
 * Annahme darüber, was das Backend sendet, statt dessen tatsächlicher
 * Ausgabe. Das ist §5.79 Teil zwei: ein Erwartungswert, der nicht aus der
 * Spezifikation kommt, prüft nur, dass sich nichts geändert hat.
 *
 * Diese Datei dreht das um. Die Mocks hier sind **absichtlich untypisiert**
 * und tragen Strings, wo ein `Decimal` herkommt — sie bilden ab, was ein
 * Backend ohne Serializer liefert. Ein `Device`-Typ als Annotation würde
 * genau das verbieten und den Test damit unmöglich machen; der Typ ist hier
 * die falsche Autorität, weil er die Behauptung ist, die sich als falsch
 * erwiesen hat.
 *
 * Die Ursache ist im Backend behoben (Feld im Serializer, plus ein Test über
 * die Feld-Annotationen aller Antwort-Modelle). Diese Tests sichern die
 * **zweite Linie**: die Normalisierung an der API-Grenze (`lib/api/zahlen.ts`)
 * und den totalen Formatter im Badge. Beide zusammen sorgen dafür, dass ein
 * künftiges Decimal-Feld ohne Serializer eine fehlende Zahl ergibt und
 * keinen Totalschaden.
 */

const DEVICE_ID = 42;

/** Wie ein Backend OHNE field_serializer antwortet: Decimal als String. */
const DEVICE_MIT_STRING_DECIMALS = {
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
  firmware_version: "4.4",
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
  valve_state: "zimmer_zu_warm",
  // Der Auslöser: String statt Zahl.
  valve_delta_k: "5.40",
  battery_state: "ok",
  // Dieselbe Klasse, nur bisher mit Serializer — hier trotzdem als String,
  // damit die Normalisierung auch für diese Felder geprüft ist.
  battery_voltage_median: "3.10",
  battery_jump_at: null,
  battery_last_voltage: "3.10",
  battery_last_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
};

const HW_STATUS = {
  status: "active",
  source: "mounted_confirmed",
  mounted_confirmed_at: new Date(Date.now() - 6 * 86400 * 1000).toISOString(),
  last_seen: null,
  frames_in_window: 3,
  window_minutes: 30,
};

async function mockApi(page: import("@playwright/test").Page) {
  // §5.54: Regex statt Glob — die Folge-URLs tragen Query-Strings.
  await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(HW_STATUS),
    }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+\/sensor-readings(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(DEVICE_MIT_STRING_DECIMALS),
    }),
  );
  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([DEVICE_MIT_STRING_DECIMALS]),
    }),
  );
}

/** Sammelt Seiten-Fehler, damit ein Absturz nicht nur als leere Liste auffällt. */
function fehlerSammler(page: import("@playwright/test").Page): string[] {
  const fehler: string[] = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  return fehler;
}

test.describe("Hotfix 07.10.2026 — Decimal als String darf nichts abschießen", () => {
  test("/devices rendert, obwohl valve_delta_k ein String ist", async ({ page }) => {
    // **Der Absturz selbst.** Vor dem Fix: "Application error: a client-side
    // exception" und eine leere Seite.
    const fehler = fehlerSammler(page);
    await mockApi(page);
    await page.goto("/devices");

    // Die Zeile ist da — und zwar mit Inhalt, nicht als Fehler-Platzhalter.
    await expect(page.getByTestId("device-hardware-cell").first()).toBeVisible();
    await expect(page.getByText("Application error")).toHaveCount(0);
    expect(
      fehler.filter((m) => m.includes("toFixed")),
      `Seiten-Fehler: ${fehler.join(" | ")}`,
    ).toHaveLength(0);
  });

  test("der Hinweis zeigt den Abstand, aus dem String gelesen", async ({ page }) => {
    // Nicht nur "stürzt nicht ab", sondern "zeigt den richtigen Wert": die
    // Normalisierung an der Grenze macht aus "5.40" die Zahl 5,4. Ohne
    // diese Zusicherung wäre auch ein Fix grün, der den Wert einfach
    // weglässt — und dann stünde der Hinweis ohne Zahl da, also mit
    // weniger Information als vorher.
    await mockApi(page);
    await page.goto(`/devices/${DEVICE_ID}`);

    const hinweis = page.getByTestId("valve-hint");
    await expect(hinweis).toContainText("Zimmer zu warm");
    await expect(hinweis).toContainText("5,4 K");
  });

  test("Gerätedetail rendert ebenfalls", async ({ page }) => {
    // Punkt 4 der Hotfix-Liste: dieselben Felder, dieselbe Badge-Komponente
    // — die Detailseite war genauso betroffen.
    const fehler = fehlerSammler(page);
    await mockApi(page);
    await page.goto(`/devices/${DEVICE_ID}`);

    await expect(page.getByTestId("hardware-status").first()).toBeVisible();
    await expect(page.getByText("Application error")).toHaveCount(0);
    expect(
      fehler.filter((m) => m.includes("toFixed")),
      `Seiten-Fehler: ${fehler.join(" | ")}`,
    ).toHaveLength(0);
  });

  test("unlesbarer Wert lässt den Hinweis stehen, nur ohne Zahl", async ({ page }) => {
    // Die Grenze der Normalisierung: was keine Zahl ist, wird `null` — und
    // `null` heißt "keine Angabe", nicht 0. Eine 0 wäre hier eine Aussage
    // ("Ist liegt 0,0 K über Soll") und damit falsch statt leer.
    await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(HW_STATUS),
      }),
    );
    await page.route(/.*\/api\/v1\/devices\/\d+\/sensor-readings(\?.*)?$/, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route(/.*\/api\/v1\/devices\/\d+(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...DEVICE_MIT_STRING_DECIMALS, valve_delta_k: "kaputt" }),
      }),
    );
    await page.goto(`/devices/${DEVICE_ID}`);

    const hinweis = page.getByTestId("valve-hint");
    await expect(hinweis).toContainText("Zimmer zu warm");
    await expect(hinweis).not.toContainText("NaN");
    await expect(hinweis).not.toContainText("0,0 K");
  });
});
