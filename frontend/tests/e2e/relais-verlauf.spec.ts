import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Der Relais-Verlauf auf der Geräteseite (17.11.2026).
 *
 * Geprüft wird, was ein Mensch von dieser Ansicht erwartet und was ihr
 * vorher gefehlt hat:
 *
 * 1. Die vier Kennzahlen stehen da, und die Heizdauer in Stunden und
 *    Minuten — nicht in Minuten mit vier Stellen.
 * 2. Eine Zeile je Tag, mit Ist-Spanne und Soll.
 * 3. Der Zeitraum-Umschalter holt **neu** (`range=7d`, `range=30d`).
 * 4. Die CSV hängt am Zeitraum, der gerade gewählt ist.
 * 5. Ein Zählerrücksprung steht neben der kWh-Zahl. Er ist in diesem Haus
 *    noch nie eingetreten; genau deshalb muss der Hinweis geprüft sein,
 *    sonst merkt niemand, wenn er beim ersten Mal nicht erscheint.
 * 6. Leerer Zeitraum: „keine Meldungen", nicht 0 Prozent.
 * 7. **Die Kacheln, die ein Relais nicht hat, sind weg** — und der
 *    Abschnitt „Verlauf der letzten 24 Stunden" samt „Noch keine
 *    Messwerte" ist es auch.
 */

const DEVICE = {
  id: 77,
  dev_eui: "beef000000000077",
  app_eui: null,
  kind: "relay" as const,
  vendor: "mclimate" as const,
  model: "16ASPM",
  label: "108",
  heating_zone_id: 9,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: "2026-11-17T07:55:00Z",
  firmware_version: "1.5",
  health_state: "healthy" as const,
  valve_state: "ok" as const,
  valve_delta_k: null,
  battery_state: "unbekannt" as const,
  created_at: "2026-11-01T10:00:00Z",
  updated_at: "2026-11-17T07:55:00Z",
  hardware_number: null,
  heating_zone: {
    id: 9,
    name: "Eingang",
    health_state: "healthy",
    room: { id: 3, number: "Rezeption", room_type: { id: 5, name: "Raum intern" } },
  },
  active_override: null,
  latest_reading: null,
};

const STAND = {
  device_id: 77,
  dev_eui: "beef000000000077",
  label: "108",
  firmware_version: "1.5",
  last_seen_at: "2026-11-17T07:55:00Z",
  commissioned_at: "2026-11-05T06:00:00Z",
  power_return_verified: true,
  overheating_recovery_verified: true,
  protection_tripped_at: null,
  protection_kind: null,
  switch_cycles: 12,
  watchdog_strategy: "expire_and_resend",
  darf_schalten: true,
  provisionierung_laeuft: false,
  relay_on: true,
  power_w: 1560,
  energy_wh: 41937,
  internal_temperature_raw: 31,
  gehaeusetemperatur_alarm: false,
  reading_time: "2026-11-17T07:55:00Z",
  change_reason: "radio_timer",
  zustand_veraltet: false,
  rssi_dbm: -97,
  snr_db: -8.5,
  offener_befehl: null,
};

function stunde(t: string, ein: number | null, ist: string | null, soll: string | null) {
  return {
    t,
    ein_prozent: ein,
    ein_minuten: ein === null ? null : Math.round((ein * 60) / 100),
    erfasste_minuten: ein === null ? 0 : 60,
    einschaltungen: ein === null ? 0 : 1,
    energie_wh: ein === null ? null : 260,
    // **Als String, wie Pydantic ein `Decimal` schickt.** Der Mock
    // bildet die Wirklichkeit ab und nicht die Bequemlichkeit: genau
    // diese Form hat am 07.10.2026 die Geräteliste abgeschossen
    // (`a.toFixed is not a function`).
    ist_mittel: ist,
    ist_min: ist,
    ist_max: ist,
    soll,
  };
}

const VERLAUF = {
  device_id: 77,
  zone_id: 9,
  zone_name: "Eingang",
  zimmer: "Rezeption",
  relais: ["108"],
  range: "24h" as const,
  range_from: "2026-11-16T08:00:00Z",
  range_to: "2026-11-17T08:00:00Z",
  timezone: "Europe/Vienna",
  stunden: [
    stunde("2026-11-16T08:00:00Z", 100, "20.00", "23"),
    stunde("2026-11-16T09:00:00Z", 50, "21.50", "23"),
    stunde("2026-11-16T10:00:00Z", null, null, null),
  ],
  tage: [
    {
      tag: "2026-11-16",
      ein_minuten: 155,
      ein_prozent: 86,
      erfasste_minuten: 180,
      einschaltungen: 3,
      energie_wh: 4030,
      ist_mittel: "20.8",
      ist_min: "20.0",
      ist_max: "21.5",
      soll_mittel: "23.0",
    },
  ],
  ein_minuten_gesamt: 155,
  anteil_gesamt: 86,
  einschaltungen_gesamt: 3,
  energie_wh_gesamt: 4030,
  ruecksprunge: 0,
};

const LEER = {
  ...VERLAUF,
  stunden: [],
  tage: [],
  ein_minuten_gesamt: 0,
  anteil_gesamt: null,
  einschaltungen_gesamt: 0,
  energie_wh_gesamt: null,
};

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

/**
 * Die Routen. **Die Reihenfolge ist nicht Geschmack:** Playwright trifft
 * die ZULETZT registrierte Route zuerst, und das Muster auf
 * `api/v1/devices/77` (mit Sternchen davor) greift auch auf
 * `/devices/77/relay` und `/relay/history`.
 *
 * (Das Sternchen-Muster steht hier in Worten und nicht als Zeichen: ein
 * Glob mit Sternchen vor dem Schrägstrich **beendet diesen Kommentar**,
 * und die Datei lässt sich dann nicht mehr übersetzen.)
 *
 * Andersherum
 * bekäme der Verlauf das Geräte-Objekt und zeigte seinen Fehler-Zustand
 * (dieselbe Falle, die in `sprint24b-relais-karte` eine Stunde gekostet
 * hat).
 */
async function mock(page: Page, verlauf: unknown): Promise<string[]> {
  const gesehen: string[] = [];
  await page.route("**/api/v1/**", (r: Route) => json(r, {}));
  await page.route("**/api/v1/devices/77/hardware-status", (r: Route) =>
    json(r, {
      device_id: 77,
      status: "ok",
      source: "window",
      mounted_confirmed_at: null,
      frames_in_window: 6,
      window_minutes: 30,
    }),
  );
  await page.route("**/api/v1/devices/77/sensor-readings*", (r: Route) => json(r, []));
  await page.route("**/api/v1/devices/77", (r: Route) => {
    if (r.request().method() !== "GET") return r.fallback();
    return json(r, DEVICE);
  });
  await page.route("**/api/v1/devices/77/relay", (r: Route) => json(r, STAND));
  await page.route("**/api/v1/devices/77/relay/history*", (r: Route) => {
    gesehen.push(new URL(r.request().url()).searchParams.get("range") ?? "");
    return json(r, verlauf);
  });
  return gesehen;
}

test.describe("Relais-Verlauf", () => {
  test("die vier Kennzahlen und die Tageszeile stehen da", async ({ page }) => {
    await mock(page, VERLAUF);
    await page.goto("/devices/77");

    const abschnitt = page.getByTestId("relay-history");
    await expect(abschnitt).toBeVisible();

    // Heizdauer als Stunden und Minuten — 155 Minuten sind 2 h 35 min.
    await expect(page.getByTestId("relay-history-heizdauer")).toContainText("2 h 35 min");
    // kWh mit einer Stelle, nicht 4030 Wh.
    await expect(page.getByTestId("relay-history-energie")).toContainText("4.0 kWh");
    await expect(abschnitt).toContainText("86 %");
    // Wofuer die Zahlen gelten: die Zone, nicht das Geraet.
    await expect(abschnitt).toContainText("Eingang");
    await expect(abschnitt).toContainText("Relais 108");

    // Das Diagramm ist gezeichnet und nicht nur angekündigt. Die Hülle
    // misst ihre Breite selbst (ChartContainer) — ohne Messung steht
    // dort ein leeres `div`, und recharts warnt in der Konsole.
    // `svg[role=application]` und nicht `svg`: die Legende bringt drei
    // eigene kleine SVGs mit, und ein nackter `svg`-Treffer wären vier.
    await expect(
      page.getByTestId("relay-history-chart").locator("svg[role='application']"),
    ).toBeVisible();

    const tabelle = page.getByTestId("relay-history-tabelle");
    await expect(tabelle).toContainText("16.11.2026");
    await expect(tabelle).toContainText("20.8 °C");
    await expect(tabelle).toContainText("(20.0–21.5)");
    await expect(tabelle).toContainText("23.0 °C");
  });

  test("ohne Rücksprung steht die Herkunft, mit Rücksprung die Warnung", async ({ page }) => {
    await mock(page, VERLAUF);
    await page.goto("/devices/77");
    await expect(page.getByTestId("relay-history-energie")).toContainText(
      "aus dem Gerätezähler",
    );

    await page.unrouteAll();
    await mock(page, { ...VERLAUF, ruecksprunge: 1 });
    await page.goto("/devices/77");
    // **Der Rücksprung erklärt eine zu kleine Zahl.** Ohne diesen Satz
    // wäre die kWh-Angabe nach einem Überlauf oder einem `0x26`
    // stillschweigend falsch.
    await expect(page.getByTestId("relay-history-energie")).toContainText(
      "1 Zählerrücksprung",
    );
    await expect(page.getByTestId("relay-history-energie")).toContainText(
      "Verbrauch davor fehlt",
    );
  });

  test("der Zeitraum-Umschalter holt neu und zieht die CSV mit", async ({ page }) => {
    const gesehen = await mock(page, VERLAUF);
    await page.goto("/devices/77");
    await expect(page.getByTestId("relay-history")).toBeVisible();

    await expect(page.getByTestId("relay-history-csv")).toHaveAttribute(
      "href",
      "/api/v1/devices/77/relay/history.csv?range=24h",
    );

    await page.getByTestId("relay-history-bereich-7d").click();
    await expect(page.getByTestId("relay-history-csv")).toHaveAttribute(
      "href",
      "/api/v1/devices/77/relay/history.csv?range=7d",
    );
    await page.getByTestId("relay-history-bereich-30d").click();
    await expect(page.getByTestId("relay-history-csv")).toHaveAttribute(
      "href",
      "/api/v1/devices/77/relay/history.csv?range=30d",
    );

    // Jeder Zeitraum ist eine eigene Abfrage — die Zusammenfassung macht
    // der Server, und ein Umschalten im Browser hätte nichts, worauf es
    // umschalten könnte.
    expect(gesehen).toContain("24h");
    expect(gesehen).toContain("7d");
    expect(gesehen).toContain("30d");
  });

  test("ein leerer Zeitraum sagt „keine Meldungen“ und nicht 0 Prozent", async ({ page }) => {
    await mock(page, LEER);
    await page.goto("/devices/77");

    const abschnitt = page.getByTestId("relay-history");
    await expect(abschnitt).toContainText("keine Meldungen");
    // Ein Strich und keine 0 kWh: eine 0 wäre eine Aussage über ein
    // Gerät, von dem wir nichts gehört haben.
    await expect(page.getByTestId("relay-history-energie")).toContainText("–");
    await expect(page.getByTestId("relay-history-tabelle")).toHaveCount(0);
  });

  test("die Kacheln, die ein Relais nicht hat, sind weg", async ({ page }) => {
    await mock(page, VERLAUF);
    await page.goto("/devices/77");
    await expect(page.getByTestId("relay-card")).toBeVisible();

    // Vorgabe des Betreibers, 16.11.2026: „leere Kacheln beim Relais
    // ausblenden". Alle vier lesen `sensor_reading` — ein 16ASPM hat
    // dort keine einzige Zeile und stand deshalb dauerhaft auf „—".
    await expect(page.getByTestId("kpi-ventilstellung")).toHaveCount(0);
    await expect(page.getByTestId("battery-card")).toHaveCount(0);
    await expect(page.getByTestId("window-backplate-card")).toHaveCount(0);
    await expect(page.getByTestId("override-card")).toHaveCount(0);

    // Der Paketverlust bleibt: er zählt Lücken im Frame-Zähler und gilt
    // für beide Gerätearten.
    await expect(page.getByTestId("paketverlust-karte")).toBeVisible();

    // Und der Abschnitt, der aus der falschen Tabelle gelesen hätte.
    await expect(page.getByText("Verlauf der letzten 24 Stunden")).toHaveCount(0);
    await expect(page.getByText("Noch keine Messwerte für dieses Gerät")).toHaveCount(0);
  });
});
