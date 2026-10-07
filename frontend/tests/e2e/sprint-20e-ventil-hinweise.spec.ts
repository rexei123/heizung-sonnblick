import { test, expect } from "@playwright/test";

import type { Device } from "@/lib/api/types";

/**
 * Sprint 20e (T7/T10) — die Ventil-Hinweise in der Oberfläche.
 *
 * **Warum dieser Badge nicht optional ist.** 20e T4 hat Engine-Layer 4 für
 * Geräte mit Montage-Nachweis stillgelegt — also für genau die Geräte, bei
 * denen er hätte anschlagen sollen. Ein montiertes Gerät, das später
 * tatsächlich abfällt, erkennt die Engine nicht mehr. Regel 3b ist der
 * Ersatz: ein Ventil ohne Kopf steht voll offen, das Zimmer wird **heiß**,
 * und das ist ohne den Backplate-Taster messbar.
 *
 * Geprüft wird:
 *
 * 1. Beide Hinweise erscheinen, mit dem gemessenen Abstand in der Erklärung.
 * 2. ``ok`` und ``unbekannt`` rendern **nichts** — eine Pille „Ventil in
 *    Ordnung" an 104 Zeilen wäre Rauschen, in dem die auffälligen Zeilen
 *    untergehen.
 * 3. Die Farben: gelb für „Ventil prüfen", rot für „Zimmer zu warm". Die
 *    Farbe folgt dem Schaden, nicht der Dringlichkeit des Handgriffs.
 */

const DEVICE_ID = 77;

const BASE_DEVICE: Device = {
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
  valve_state: "ok",
  valve_delta_k: null,
  battery_state: "ok",
  battery_voltage_median: 3.1,
  battery_jump_at: null,
  battery_last_voltage: 3.1,
  battery_last_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
};

async function mockDetail(
  page: import("@playwright/test").Page,
  overrides: Partial<Device>,
) {
  const device = { ...BASE_DEVICE, ...overrides };
  // §5.54: Regex statt Glob — die Folge-URLs tragen Query-Strings.
  await page.route(/.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "active",
        source: "mounted_confirmed",
        mounted_confirmed_at: new Date(Date.now() - 6 * 86400 * 1000).toISOString(),
        last_seen: null,
        frames_in_window: 3,
        window_minutes: 30,
      }),
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

test.describe("Sprint 20e — Ventil-Hinweise", () => {
  test("Zimmer zu warm: roter Hinweis mit gemessenem Abstand", async ({ page }) => {
    // Das Bild eines abgenommenen Thermostatkopfs: der Stift wird von der
    // Feder herausgedrückt, das Ventil steht offen, das Zimmer heizt durch.
    await mockDetail(page, { valve_state: "zimmer_zu_warm", valve_delta_k: 6.2 });
    await page.goto(`/devices/${DEVICE_ID}`);

    const hinweis = page.getByTestId("valve-hint");
    await expect(hinweis).toContainText("Zimmer zu warm");
    await expect(hinweis).toContainText("6,2 K");
    // Der Hauptverdacht steht zuerst, weil er der teuerste ist.
    await expect(hinweis).toContainText("Thermostatkopf abgenommen");
    await expect(hinweis.locator("span").first()).toHaveClass(/text-danger/);
  });

  test("Ventil klemmt zu: gelber Hinweis, beide Ursachen genannt", async ({ page }) => {
    await mockDetail(page, { valve_state: "ventil_klemmt_zu", valve_delta_k: 4.0 });
    await page.goto(`/devices/${DEVICE_ID}`);

    const hinweis = page.getByTestId("valve-hint");
    await expect(hinweis).toContainText("Ventil prüfen");
    await expect(hinweis).toContainText("4,0 K");
    // „0 %" heißt entweder zu oder nicht kalibriert, und das ist aus den
    // Daten nicht zu unterscheiden. Der Text nennt beides statt zu raten.
    await expect(hinweis).toContainText("klemmt oder ist nicht kalibriert");
    const pille = hinweis.locator("span").first();
    await expect(pille).toHaveClass(/text-warning/);
    await expect(pille).not.toHaveClass(/text-danger/);
  });

  test("ok rendert nichts", async ({ page }) => {
    // Eine Pille „Ventil in Ordnung" an jeder Zeile wäre Rauschen, in dem
    // die zwei auffälligen Zeilen untergehen — und genau das soll der
    // Hinweis verhindern.
    await mockDetail(page, { valve_state: "ok", valve_delta_k: null });
    await page.goto(`/devices/${DEVICE_ID}`);

    await expect(page.getByTestId("hardware-status").first()).toBeVisible();
    await expect(page.getByTestId("valve-hint")).toHaveCount(0);
  });

  test("unbekannt rendert ebenfalls nichts", async ({ page }) => {
    // „zu wenige Messwerte" ist eine echte Information, aber sie gehört auf
    // die Offline-Achse (health_state), die daneben schon steht. Zwei
    // Badges für dieselbe Ursache wären zwei Melder für ein Problem.
    await mockDetail(page, { valve_state: "unbekannt", valve_delta_k: null });
    await page.goto(`/devices/${DEVICE_ID}`);

    await expect(page.getByTestId("hardware-status").first()).toBeVisible();
    await expect(page.getByTestId("valve-hint")).toHaveCount(0);
  });

  test("ohne Abstand bleibt der Text sinnvoll", async ({ page }) => {
    // Der Abstand ist optional; ein Urteil ohne Zahl darf keine Lücke im
    // Satz hinterlassen („Ist liegt über Soll" statt „Ist liegt  über Soll").
    await mockDetail(page, { valve_state: "zimmer_zu_warm", valve_delta_k: null });
    await page.goto(`/devices/${DEVICE_ID}`);

    const hinweis = page.getByTestId("valve-hint");
    await expect(hinweis).toContainText("Ist liegt über Soll");
    await expect(hinweis).not.toContainText("undefined");
    await expect(hinweis).not.toContainText("null");
  });
});
