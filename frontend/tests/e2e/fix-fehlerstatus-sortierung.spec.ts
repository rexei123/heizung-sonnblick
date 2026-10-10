import { expect, test, type Page } from "@playwright/test";

import type { Device } from "@/lib/api/types";

/**
 * Der Sortier-Befund vom 08.10.2026, als Test.
 *
 * Auf `/devices` stand Gerät 001 oben, während **keines** der 14 Geräte mit
 * „Zimmer zu warm" nach oben kam — und 102 („Tauschen · 2,6 V"), das am
 * 05.10. noch oben stand, war nach unten gerutscht.
 *
 * Zwei Ursachen, und die zweite ist die interessantere:
 *
 * 1. **Die Ventil-Achse fehlte ganz.** Sprint 20e T7/T10 hat `valve_state`
 *    eingeführt und diesen Konsumenten nicht nachgezogen — dieselbe
 *    Auslassung wie der fehlende TypeScript-Typ in 20f-b und der fehlende
 *    `field_serializer` im Hotfix vom 07.10.
 * 2. **`health_state` gewann grundsätzlich.** Das war vertretbar, solange
 *    `silent` erst nach 24 Stunden eintrat. Sprint 20e T6 hat die Grenze auf
 *    3 Stunden gesenkt; seither ist `silent` häufig und oft vorübergehend
 *    und verdeckte als Trumpf die Geräte mit Handlungsbedarf. 102 ist also
 *    nicht abgerutscht, sondern überholt worden.
 *
 * Geprüft wird gegen `data-status-score`, nicht nur gegen die Reihenfolge:
 * bei Gleichstand entscheidet die alphabetische Zweitsortierung, und dann
 * prüft ein Reihenfolge-Test etwas anderes als er meint.
 */

const iso = (msAgo = 0) => new Date(Date.now() - msAgo).toISOString();

function makeDevice(
  id: number,
  label: string,
  zusatz: Partial<Device> = {},
): Device {
  return {
    id,
    dev_eui: `00112233445566${id.toString().padStart(2, "0")}`,
    app_eui: null,
    kind: "thermostat",
    vendor: "mclimate",
    model: "Vicki",
    label,
    heating_zone_id: null,
    // 20e-b: der Spiegel verlangt die drei Referenz-Felder. Hier steuert
    // nur `valve_state` die Sortierung — die Referenz ist Beiwerk und
    // bleibt auf dem Normalfall.
    valve_referenz: "unbelegt",
    valve_referenz_median_c: 20.0,
    valve_referenz_delta_k: null,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: iso(5 * 60 * 1000),
    created_at: iso(86400 * 1000),
    updated_at: iso(),
    firmware_version: "4.4",
    health_state: "healthy",
    hardware_number: null,
    heating_zone: null,
    active_override: null,
    latest_reading: null,
    valve_state: "ok",
    valve_delta_k: null,
    battery_state: "ok",
    battery_voltage_median: 3.2,
    battery_jump_at: null,
    battery_last_voltage: 3.2,
    battery_last_at: iso(5 * 60 * 1000),
    ...zusatz,
  };
}

async function mockDevices(page: Page, devices: Device[]) {
  await page.route("**/api/v1/devices*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(devices),
    }),
  );
  await page.route("**/api/v1/devices/*/hardware-status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "active",
        source: "mounted_confirmed",
        mounted_confirmed_at: iso(6 * 86400 * 1000),
        last_seen: null,
        frames_in_window: 3,
        window_minutes: 30,
      }),
    }),
  );
}

test.describe("Fehlerstatus-Sortierung — Handlungsbedarf vor Datenlage", () => {
  test("die Rangfolge der sechs Stufen, an data-status-score geprüft", async ({ page }) => {
    await mockDevices(page, [
      makeDevice(1, "a-ok"),
      makeDevice(2, "b-batt-warn", { battery_state: "warn", battery_voltage_median: 2.8 }),
      makeDevice(3, "c-degraded", { health_state: "degraded" }),
      makeDevice(4, "d-ventil-zu", { valve_state: "ventil_klemmt_zu", valve_delta_k: 4.0 }),
      makeDevice(5, "e-silent", { health_state: "silent" }),
      makeDevice(6, "f-batt-kritisch", {
        battery_state: "kritisch",
        battery_voltage_median: 2.6,
      }),
      makeDevice(7, "g-zu-warm", { valve_state: "zimmer_zu_warm", valve_delta_k: 6.2 }),
    ]);
    await page.goto("/devices");

    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(7);

    // Absteigend: 4 silent > 3 ventil zu > 2 batt-kritisch = 2 zu warm
    // (alphabetisch) > 1 warn = 1 degraded > 0 ok.
    //
    // `zimmer_zu_warm` steht im Informations-Band, nicht oben — Übergang
    // bis Sprint 20e-b, Begründung an `RANG_ZIMMER_ZU_WARM`.
    await expect(rows.nth(0)).toContainText("e-silent");
    await expect(rows.nth(0)).toHaveAttribute("data-status-score", "4");
    await expect(rows.nth(1)).toContainText("d-ventil-zu");
    await expect(rows.nth(1)).toHaveAttribute("data-status-score", "3");
    // Gleichstand bei 2: f-batt-kritisch vor g-zu-warm (alphabetisch).
    await expect(rows.nth(2)).toContainText("f-batt-kritisch");
    await expect(rows.nth(2)).toHaveAttribute("data-status-score", "2");
    await expect(rows.nth(3)).toContainText("g-zu-warm");
    await expect(rows.nth(3)).toHaveAttribute("data-status-score", "2");
    // Gleichstand bei 1 — die Zweitsortierung entscheidet, und genau
    // deshalb steht hier die Zahl und nicht nur die Position.
    await expect(rows.nth(4)).toHaveAttribute("data-status-score", "1");
    await expect(rows.nth(5)).toHaveAttribute("data-status-score", "1");
    await expect(rows.nth(6)).toContainText("a-ok");
    await expect(rows.nth(6)).toHaveAttribute("data-status-score", "0");
  });

  test("„Zimmer zu warm“ zählt, steht aber unter einem stillen Gerät", async ({
    page,
  }) => {
    // **Die Regressions-Wand für den Befund vom 08.10.** Vorher war
    // „Zimmer zu warm" gar nicht im Score, das Gerät landete bei 0 und
    // stand ganz unten.
    //
    // Es zählt jetzt (2 > 0), steht aber **nicht** oben: die Regel liefert
    // bis Sprint 20e-b Fehlalarme (15 Meldungen, zwei davon echt), und 13
    // Falschmeldungen an der Spitze verdecken jedes stille Gerät. Mit 20e-b
    // wird der Rang gehoben.
    await mockDevices(page, [
      makeDevice(20, "a-still", { health_state: "silent" }),
      makeDevice(21, "z-zu-warm", { valve_state: "zimmer_zu_warm", valve_delta_k: 6.2 }),
    ]);
    await page.goto("/devices");

    const rows = page.locator("tbody tr");
    await expect(rows.nth(0)).toContainText("a-still");
    await expect(rows.nth(0)).toHaveAttribute("data-status-score", "4");
    await expect(rows.nth(1)).toContainText("z-zu-warm");
    await expect(rows.nth(1)).toHaveAttribute("data-status-score", "2");
  });

  test("der Übergangswert ist bewusst und wird mit 20e-b gehoben", async ({ page }) => {
    // **Dieser Test soll mit 20e-b fallen.** Er hält den Übergangswert
    // fest, damit das Heben eine Entscheidung ist und keine Entdeckung —
    // und damit niemand den Wert aus Versehen hebt, solange die Regel noch
    // Fehlalarme liefert.
    //
    // Was mit 20e-b zu tun ist: `RANG_ZIMMER_ZU_WARM` auf 5, diesen Test
    // und die beiden Reihenfolge-Tests darüber anpassen, den Vermerk im
    // 20e-b-Brief abhaken.
    await mockDevices(page, [
      makeDevice(60, "zu-warm", { valve_state: "zimmer_zu_warm", valve_delta_k: 9.9 }),
    ]);
    await page.goto("/devices");

    await expect(page.locator("tbody tr").first()).toHaveAttribute(
      "data-status-score",
      "2",
    );
  });

  test("Funkstille steht über niedriger Spannung — die Betriebsregel", async ({
    page,
  }) => {
    // **Umgedreht am 08.10.2026, und zwar gegen meine eigene Begründung
    // von einem Tag vorher.** Dieser Test verlangte „batt-kritisch über
    // silent", weil der 24-h-Median robuster sei als ein Einzelwert.
    //
    // Die Betriebsregel sagt das Gegenteil, mit einem Befund: getauscht
    // wird bei drei Stunden Funkstille, nicht bei einer Spannung. Gerät 102
    // meldete am 04.10. 2,6 V — ein gehaltener Einzelwert unter Last, fCnt
    // lückenlos, seit 06.10. wieder 3,5 V. Ein Einbruch, der über Stunden
    // anhält, überlebt auch den Median.
    //
    // Namen gegen die Erwartung alphabetisch: fiele die Sortierung auf die
    // Zweitsortierung zurück, stünde „a-spannung-niedrig" oben.
    await mockDevices(page, [
      makeDevice(30, "a-spannung-niedrig", {
        battery_state: "kritisch",
        battery_voltage_median: 2.6,
      }),
      makeDevice(31, "z-still", { health_state: "silent" }),
    ]);
    await page.goto("/devices");

    const rows = page.locator("tbody tr");
    await expect(rows.nth(0)).toContainText("z-still");
    await expect(rows.nth(0)).toHaveAttribute("data-status-score", "4");
    await expect(rows.nth(1)).toContainText("a-spannung-niedrig");
    await expect(rows.nth(1)).toHaveAttribute("data-status-score", "2");
  });

  test("unbekannte Achsen-Werte zählen nicht als Problem", async ({ page }) => {
    // `valve_state: "unbekannt"` heißt „zu wenige Messwerte", nicht
    // „auffällig" — es gehört auf die Offline-Achse, die daneben steht.
    // Dasselbe für `battery_state: "unbekannt"`. Beide dürfen ein gesundes
    // Gerät nicht nach oben schieben, sonst stünde die halbe Liste oben.
    await mockDevices(page, [
      makeDevice(40, "a-unbekannt", {
        valve_state: "unbekannt",
        battery_state: "unbekannt",
        battery_voltage_median: null,
      }),
      makeDevice(41, "z-warn", { battery_state: "warn", battery_voltage_median: 2.8 }),
    ]);
    await page.goto("/devices");

    const rows = page.locator("tbody tr");
    await expect(rows.nth(0)).toContainText("z-warn");
    await expect(rows.nth(0)).toHaveAttribute("data-status-score", "1");
    await expect(rows.nth(1)).toHaveAttribute("data-status-score", "0");
  });

  test("sort=label lässt den Score unberührt", async ({ page }) => {
    // Die Zweitsortierung darf die Hauptsortierung nicht ersetzen: bei
    // `?sort=label` zählt nur das Label, und das Attribut bleibt trotzdem
    // am Element — es beschreibt das Gerät, nicht die Reihenfolge.
    await mockDevices(page, [
      makeDevice(50, "z-zu-warm", { valve_state: "zimmer_zu_warm", valve_delta_k: 6.2 }),
      makeDevice(51, "a-ok"),
    ]);
    await page.goto("/devices?sort=label");

    const rows = page.locator("tbody tr");
    await expect(rows.nth(0)).toContainText("a-ok");
    await expect(rows.nth(1)).toContainText("z-zu-warm");
    await expect(rows.nth(1)).toHaveAttribute("data-status-score", "2");
  });
});
