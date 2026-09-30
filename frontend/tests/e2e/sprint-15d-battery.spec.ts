import { test, expect, type Page } from "@playwright/test";

/**
 * Sprint 15d (AE-65) — Batterie-Sichtbarkeit (PR2 Frontend).
 *
 * - BatteryBadge in der /devices-Tabelle: 3+1 Zustände aus device.battery_state.
 * - statusScore-Redesign: Sortierung über BEIDE Health-Achsen (max), die
 *   health_state-Achse schlägt die Batterie-Achse (offline > batt-kritisch).
 *
 * Backend gemockt via Route-Interception (kein FastAPI nötig), Muster wie
 * devices.spec.ts.
 */

const NOW = Date.now();
const iso = (offsetMs = 0) => new Date(NOW - offsetMs).toISOString();

type HealthState = "healthy" | "degraded" | "silent" | "suspicious";
type BatteryState = "ok" | "warn" | "kritisch" | "unbekannt";

interface BatterieZusatz {
  /** `battery_jump_at` — Batteriewechsel erkannt. */
  jumpAt?: string | null;
  /** `battery_last_voltage` — letzter bekannter Wert, auch ohne Stufe. */
  lastVolts?: number | null;
  /** `battery_last_at` — Zeitpunkt dieses Werts. */
  lastAt?: string | null;
}

function makeDevice(
  id: number,
  label: string,
  healthState: HealthState,
  batteryState: BatteryState,
  batteryVolts: number | null,
  zusatz: BatterieZusatz = {},
) {
  return {
    id,
    dev_eui: id.toString(16).padStart(16, "0"),
    app_eui: null,
    kind: "thermostat" as const,
    vendor: "mclimate" as const,
    model: "vicki",
    label,
    heating_zone_id: null,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: iso(5 * 60 * 1000),
    firmware_version: "4.2",
    health_state: healthState,
    battery_state: batteryState,
    // Sprint 20 (AE-72): der 24-h-Median ist die Quelle der Zahl am Badge.
    battery_voltage_median: batteryVolts,
    battery_jump_at: zusatz.jumpAt ?? null,
    // Nachbesserung 30.09.: der letzte bekannte Wert wird immer mitgegeben.
    // Default ist der Median — ein Gerät mit Stufe hat auch einen letzten
    // Wert, und die Tests sollen nicht versehentlich den Fall "nie gemeldet"
    // treffen, wenn sie ihn nicht meinen.
    // `=== undefined` und nicht `??`: ein ausdrueckliches `null` heisst
    // „nie gemeldet" und muss den Default schlagen. `null ?? x` ergibt x —
    // damit haette der Fall „nie gemeldet" nie getestet werden koennen.
    battery_last_voltage:
      zusatz.lastVolts === undefined ? batteryVolts : zusatz.lastVolts,
    battery_last_at:
      zusatz.lastAt === undefined ? iso(5 * 60 * 1000) : zusatz.lastAt,
    created_at: iso(86400 * 1000),
    updated_at: iso(),
    hardware_number: null,
    heating_zone: null,
    active_override: null,
    latest_reading:
      batteryVolts === null
        ? null
        : {
            valve_position: 40,
            open_window: false,
            attached_backplate: true,
            temperature: 21.0,
            battery_voltage: batteryVolts,
            recorded_at: iso(5 * 60 * 1000),
          },
  };
}

async function mockDevices(page: Page, devices: unknown[]) {
  await page.route("**/api/v1/devices*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(devices),
    }),
  );
  // HardwareStatusBadge fetcht je Gerät /hardware-status — generisch mocken.
  await page.route("**/api/v1/devices/*/hardware-status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "inactive",
        last_seen: null,
        frames_in_window: 0,
        window_minutes: 30,
      }),
    }),
  );
}

test.describe("Sprint 15d — Batterie-Badge + statusScore", () => {
  test("BatteryBadge zeigt 3+1 Zustände aus battery_state, Prozent im title", async ({ page }) => {
    await mockDevices(page, [
      makeDevice(1, "Batt-OK", "healthy", "ok", 3.2),
      makeDevice(2, "Batt-Warn", "healthy", "warn", 2.9),
      makeDevice(3, "Batt-Kritisch", "healthy", "kritisch", 2.8),
      makeDevice(4, "Batt-Unbekannt", "healthy", "unbekannt", null),
    ]);
    await page.goto("/devices?sort=label");

    const badges = page.getByTestId("device-battery-cell").getByTestId("battery-badge");
    await expect(badges).toHaveCount(4);
    // sort=label -> alphabetisch: Kritisch, OK, Unbekannt, Warn
    await expect(page.locator("tbody tr").nth(0).getByTestId("battery-badge")).toHaveAttribute(
      "data-battery",
      "kritisch",
    );
    // Sprint 20 (AE-72): Spannung SICHTBAR neben der Stufe, und zwar der
    // Median — nicht der letzte Frame.
    await expect(page.locator("tbody tr").nth(0).getByTestId("battery-badge")).toContainText(
      "Batterie kritisch · 2,8 V",
    );
    await expect(page.locator("tbody tr").nth(0).getByTestId("battery-badge")).toHaveAttribute(
      "title",
      /2,8 V/,
    );
    // unbekannt ohne Reading -> Hint-title, keine Zahl.
    const unknownBadge = page
      .locator("tbody tr")
      .filter({ hasText: "Batt-Unbekannt" })
      .getByTestId("battery-badge");
    await expect(unknownBadge).toHaveAttribute("data-battery", "unbekannt");
  });

  test("statusScore: offline (silent) schlägt batt-kritisch (health-Achse > batt-Achse)", async ({
    page,
  }) => {
    // Scores: Offline-OK=4 (silent), Online-Kritisch=2, Online-Warn=1, Online-OK=0.
    await mockDevices(page, [
      makeDevice(10, "Online-OK", "healthy", "ok", 3.4),
      makeDevice(11, "Online-Warn", "healthy", "warn", 2.9),
      makeDevice(12, "Online-Kritisch", "healthy", "kritisch", 2.8),
      makeDevice(13, "Offline-OK", "silent", "ok", 3.4),
    ]);
    // Default-Sortierung = Fehlerstatus (kein ?sort).
    await page.goto("/devices");

    const rows = page.locator("tbody tr");
    await expect(rows).toHaveCount(4);
    // Erwartete Reihenfolge absteigend nach Score: 4 > 2 > 1 > 0.
    await expect(rows.nth(0)).toContainText("Offline-OK"); // silent = 4 (schlägt kritisch=2)
    await expect(rows.nth(1)).toContainText("Online-Kritisch"); // batt-kritisch = 2
    await expect(rows.nth(2)).toContainText("Online-Warn"); // batt-warn = 1
    await expect(rows.nth(3)).toContainText("Online-OK"); // healthy+ok = 0
  });

  // ------------------------------------------------------------------
  // Nachbesserung 30.09.2026: nie ein Badge ohne Spannung
  // ------------------------------------------------------------------
  //
  // Befund auf heizung-test: die Geräteliste zeigte reihenweise „Batterie
  // unbekannt" ohne Zahl. Für den Hotelier ist das wertlos — er weiß danach
  // so viel wie vorher, und „unbekannt" liest sich wie ein Defekt, obwohl
  // die Zelle voll sein kann.

  test("ohne Stufe, aber mit letztem Wert: Spannung und Alter", async ({ page }) => {
    // Ein oder zwei Messwerte reichen nicht für einen Median (drei sind
    // nötig), also bleibt battery_state="unbekannt" — die Stufe ist wirklich
    // nicht berechenbar. Die Zahl gibt es trotzdem.
    await mockDevices(page, [
      makeDevice(20, "Zwei-Werte", "healthy", "unbekannt", null, {
        lastVolts: 3.5,
        lastAt: iso(2 * 60 * 60 * 1000),
      }),
    ]);
    await page.goto("/devices");

    const badge = page.getByTestId("device-battery-cell").getByTestId("battery-badge");
    await expect(badge).toContainText("3,5 V");
    await expect(badge).toContainText("vor 2 h");
    // Das Wort darf nicht mehr allein dastehen.
    await expect(badge).not.toContainText("Batterie unbekannt");
    // Neutral, nicht rot: eine fehlende Stufe ist kein Mangel am Gerät.
    await expect(badge).toHaveAttribute("data-battery", "unbekannt");
  });

  test("Batteriewechsel erkannt: Grund plus Spannung", async ({ page }) => {
    // Nach einem Wechsel zählt nur das Fenster ab dem Sprung. Bis drei
    // Messwerte darin sind, gibt es keine Stufe — das ist eine halbe Stunde
    // Wartezeit und kein Fehler. Ohne diesen Text sucht der Hotelier einen.
    await mockDevices(page, [
      makeDevice(21, "Gewechselt", "healthy", "unbekannt", null, {
        jumpAt: iso(10 * 60 * 1000),
        lastVolts: 3.5,
        lastAt: iso(5 * 60 * 1000),
      }),
    ]);
    await page.goto("/devices");

    const badge = page.getByTestId("device-battery-cell").getByTestId("battery-badge");
    await expect(badge).toContainText("Batteriewechsel erkannt");
    await expect(badge).toContainText("3,5 V");
    await expect(badge).not.toContainText("Batterie unbekannt");
  });

  test("nie eine Spannung gemeldet: Wort ohne Zahl", async ({ page }) => {
    // Der einzige Fall, in dem das Wort ohne Zahl richtig ist. Ein Gerät, das
    // nur Zeilen von vor Migration 0024 hat, hat nie eine Spannung gemeldet.
    await mockDevices(page, [
      makeDevice(22, "Nie-Gemeldet", "healthy", "unbekannt", null, {
        lastVolts: null,
        lastAt: null,
      }),
    ]);
    await page.goto("/devices");

    const badge = page.getByTestId("device-battery-cell").getByTestId("battery-badge");
    await expect(badge).toContainText("Batterie unbekannt");
    // Keine erfundene Zahl daneben.
    await expect(badge).not.toContainText("V");
    await expect(badge).toHaveAttribute(
      "title",
      "Dieses Gerät hat noch nie eine Spannung gemeldet.",
    );
  });

  test("mit Stufe gewinnt der Median, nicht der letzte Wert", async ({ page }) => {
    // Die Gegenprobe zur Nachbesserung: sobald eine Stufe da ist, steht der
    // Median in der Pille. Hier liegen die beiden absichtlich auseinander —
    // der letzte Frame ist unter Motorlast eingebrochen (2,6 V), der Median
    // über 24 Stunden ist 3,1 V. Wer hier den letzten Wert zeigt, baut genau
    // den Fehlbefund nach, der Gerät 001 als „kritisch" auswies.
    await mockDevices(page, [
      makeDevice(23, "Lastabfall", "healthy", "ok", 3.1, {
        lastVolts: 2.6,
        lastAt: iso(5 * 60 * 1000),
      }),
    ]);
    await page.goto("/devices");

    const badge = page.getByTestId("device-battery-cell").getByTestId("battery-badge");
    await expect(badge).toContainText("Batterie OK · 3,1 V");
    await expect(badge).not.toContainText("2,6 V");
  });
});
