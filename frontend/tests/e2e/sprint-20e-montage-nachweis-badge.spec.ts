import { test, expect } from "@playwright/test";

import type { HardwareStatusResponse } from "@/lib/api/types";

/**
 * Sprint 20e (T5) — der Montage-Nachweis schlägt den Taster, auch in der Pille.
 *
 * **Der Befund hinter dem Sprint.** Der Backplate-Taster meldet im Haus zu
 * oft `false`, obwohl das Gerät sitzt. Die Engine schaltete daraufhin ein
 * belegtes Zimmer in den Frostschutz, und die Pille sagte „Nicht montiert"
 * über ein Gerät, das an der Wand hing.
 *
 * Seit 20e urteilt für ein zugeordnetes Gerät mit
 * `device.mounted_confirmed_at` der Nachweis — im Backend-Endpoint
 * (`source="mounted_confirmed"`) und in Engine-Layer 4 aus derselben Quelle.
 * Zwei Urteile zur selben Frage wären die Sorte Drift, die §5.53 beschreibt.
 *
 * Was hier geprüft wird:
 *
 * 1. `source="mounted_confirmed"` + kein True-Frame -> **Montiert**, und die
 *    Unterzeile nennt den Beleg statt des Fensters.
 * 2. Der Zusatz „Taster meldet aktuell nicht" erscheint genau dann, wenn
 *    `last_seen === null` — das ist die Diagnose, die den sticky-Zustand von
 *    einer frischen Meldung unterscheidbar macht.
 * 3. `source="window"` bleibt unverändert (Regression gegen Sprint 17 / 20).
 * 4. Die Rohwert-Kachel ist als Diagnose gekennzeichnet, damit „abgenommen"
 *    dort nicht als Widerspruch zur Pille gelesen wird.
 */

const DEVICE_ID = 42;

const DEVICE = {
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
  // Der Rohwert sagt „abgenommen" — genau der Fall, der 20e ausgelöst hat.
  latest_reading: {
    time: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
    temperature: 21.4,
    setpoint: 21,
    valve_position: 0,
    battery_percent: null,
    battery_voltage: 3.1,
    rssi_dbm: -92,
    snr_db: 8,
    open_window: false,
    attached_backplate: false,
    broken_sensor: null,
    fcnt: 1234,
  },
  valve_state: "ok" as const,
  valve_delta_k: null,
  battery_state: "ok",
};

const NACHWEIS_AM = new Date(Date.now() - 6 * 86400 * 1000).toISOString();

/** Urteil aus dem Nachweis, Taster schweigt im Fenster. */
const HW_STICKY_STUMM: HardwareStatusResponse = {
  status: "active",
  source: "mounted_confirmed",
  mounted_confirmed_at: NACHWEIS_AM,
  last_seen: null,
  frames_in_window: 3,
  window_minutes: 30,
};

/** Urteil aus dem Nachweis, Taster meldet zusätzlich frisch „montiert". */
const HW_STICKY_MELDET: HardwareStatusResponse = {
  ...HW_STICKY_STUMM,
  last_seen: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
};

/** Bestand: Urteil aus dem Fenster. */
const HW_FENSTER: HardwareStatusResponse = {
  status: "active",
  source: "window",
  mounted_confirmed_at: null,
  last_seen: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
  frames_in_window: 3,
  window_minutes: 30,
};

async function mockDetailPage(
  page: import("@playwright/test").Page,
  hw: HardwareStatusResponse,
) {
  // §5.54: Regex statt Glob — die Folge-URLs tragen Query-Strings.
  await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(hw) }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+\/sensor-readings(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/devices\/\d+(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(DEVICE) }),
  );
}

test.describe("Sprint 20e — Montage-Nachweis in der Oberfläche", () => {
  test("Nachweis gilt, obwohl der Taster im Fenster nichts meldet", async ({ page }) => {
    await mockDetailPage(page, HW_STICKY_STUMM);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Montiert");
    await expect(badge).not.toContainText("Nicht montiert");
    // Der Beleg, nicht das Fenster.
    await expect(badge).toContainText(/Montage belegt:/);
    await expect(badge).not.toContainText("Montiert zuletzt:");
  });

  test("Bei stummem Taster steht der Diagnose-Zusatz in der Unterzeile", async ({ page }) => {
    // Das ist der eigentliche Nutzen der Zeile: sie sagt dem Hausmeister,
    // dass das Urteil am Nachweis hängt und der Taster gerade schweigt.
    // Ohne den Zusatz wäre die sticky-Anzeige von einer frischen Meldung
    // nicht zu unterscheiden.
    await mockDetailPage(page, HW_STICKY_STUMM);
    await page.goto(`/devices/${DEVICE_ID}`);

    await expect(page.getByTestId("hardware-status").first()).toContainText(
      "Taster meldet aktuell nicht",
    );
  });

  test("Meldet der Taster wieder, verschwindet der Zusatz", async ({ page }) => {
    // Gegenprobe zum Test darüber: derselbe Nachweis, nur mit ``last_seen``.
    // Ohne diesen Test wäre ein fest eingebauter Zusatz ebenfalls grün.
    await mockDetailPage(page, HW_STICKY_MELDET);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText(/Montage belegt:/);
    await expect(badge).not.toContainText("Taster meldet aktuell nicht");
  });

  test("Ohne Nachweis urteilt weiter das Fenster", async ({ page }) => {
    // Regression gegen Sprint 17 / 20: der Bestandspfad ist unberührt.
    await mockDetailPage(page, HW_FENSTER);
    await page.goto(`/devices/${DEVICE_ID}`);

    const badge = page.getByTestId("hardware-status").first();
    await expect(badge).toContainText("Montiert");
    await expect(badge).toContainText("Montiert zuletzt:");
    await expect(badge).not.toContainText("Montage belegt");
  });

  test("Die Rohwert-Kachel ist als Diagnose gekennzeichnet", async ({ page }) => {
    // Hier steht „abgenommen", oben „Montiert". Das ist kein Widerspruch,
    // sondern Urteil gegen Rohwert — ohne die Kennzeichnung läse man die
    // beiden Zeilen als zwei Antworten auf dieselbe Frage und würde der
    // falschen glauben, nämlich der weiter unten.
    await mockDetailPage(page, HW_STICKY_STUMM);
    await page.goto(`/devices/${DEVICE_ID}`);

    const kachel = page.getByTestId("window-backplate-card");
    await expect(kachel).toContainText("Rohwerte des letzten Frames");
    await expect(kachel).toContainText("Der Montage-Status steht oben");
    await expect(kachel).toContainText("abgenommen");
    await expect(page.getByTestId("hardware-status").first()).toContainText("Montiert");
  });
});
