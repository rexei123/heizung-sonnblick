import { test, expect, type Page } from "@playwright/test";

/**
 * Sprint 14a — /devices-Liste (3 Spalten) + /devices/[id]-Detail
 * (2 Karten + 7 Kacheln + Inline-Edit hardware_number).
 *
 * Backend gemockt via Route-Interception (CI-tauglich, kein FastAPI noetig).
 * Device-Mocks spiegeln das enriched DeviceRead-Schema (Sprint 14a T3):
 * heating_zone (Nested) / hardware_number / active_override / latest_reading.
 */

const NOW = Date.now();
const iso = (offsetMs = 0) => new Date(NOW - offsetMs).toISOString();

const ASSIGNED_DEVICE = {
  id: 42,
  dev_eui: "0011223344556677",
  app_eui: null,
  kind: "thermostat",
  vendor: "mclimate",
  model: "vicki",
  label: "Vicki-Bad-102",
  heating_zone_id: 7,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: iso(5 * 60 * 1000),
  firmware_version: "4.2",
  health_state: "healthy",
  created_at: iso(86400 * 1000),
  updated_at: iso(),
  hardware_number: "MDC5419731K6UF",
  heating_zone: {
    id: 7,
    name: "Bad",
    health_state: "degraded",
    room: { id: 3, number: "102", room_type: { id: 1, name: "Doppelzimmer" } },
  },
  active_override: null,
  latest_reading: {
    valve_position: 42,
    open_window: false,
    attached_backplate: true,
    recorded_at: iso(5 * 60 * 1000),
  },
};

const POOL_DEVICE = {
  id: 43,
  dev_eui: "aabbccddeeff0011",
  app_eui: null,
  kind: "thermostat",
  vendor: "mclimate",
  model: "vicki",
  label: "Reserve-01",
  heating_zone_id: null,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: iso(5 * 60 * 1000),
  firmware_version: null,
  health_state: "silent",
  created_at: iso(86400 * 1000),
  updated_at: iso(),
  hardware_number: null,
  heating_zone: null,
  active_override: null,
  latest_reading: null,
};

const SAMPLE_READINGS = [
  {
    time: iso(60 * 60 * 1000),
    fcnt: 3,
    temperature: 22.4,
    setpoint: 21.0,
    valve_position: 80,
    battery_percent: 75,
    rssi_dbm: -82,
    snr_db: 8.0,
    open_window: false,
    attached_backplate: true,
  },
];

const HW_STATUS = {
  status: "active",
  last_seen: iso(5 * 60 * 1000),
  frames_in_window: 3,
  window_minutes: 30,
};

async function mockHardwareStatus(page: Page) {
  await page.route("**/api/v1/devices/*/hardware-status", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HW_STATUS) }),
  );
}

// ---------------------------------------------------------------------------
// /devices-Liste (3 Spalten, D4)
// ---------------------------------------------------------------------------

test.describe("Sprint 14a — /devices-Liste (3 Spalten)", () => {
  test("3 Spalten Bezeichnung/Zuordnung/Status, DevEUI/Hersteller/Aktiv entfernt", async ({
    page,
  }) => {
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([ASSIGNED_DEVICE, POOL_DEVICE]),
      }),
    );
    await mockHardwareStatus(page);

    await page.goto("/devices");

    await expect(page.getByRole("heading", { level: 1, name: "Geräte" })).toBeVisible();
    // Genau die drei Spalten-Header.
    await expect(page.locator("th")).toHaveText(["Bezeichnung", "Zuordnung", "Status"]);
    // DevEUI ist nicht mehr in der Liste.
    await expect(page.getByText("0011223344556677")).toHaveCount(0);
    // §5.20: Untertitel-Wording ohne „Vicki".
    await expect(page.getByText(/Thermostate, Sensoren/)).toBeVisible();
  });

  test("Zuordnung-Spalte: Zimmer · Zone bzw. Reserve-Pool", async ({ page }) => {
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([ASSIGNED_DEVICE, POOL_DEVICE]),
      }),
    );
    await mockHardwareStatus(page);

    await page.goto("/devices");

    const zuordnungen = page.getByTestId("device-zuordnung");
    await expect(zuordnungen.filter({ hasText: "102" })).toContainText("Bad");
    await expect(zuordnungen.filter({ hasText: "Reserve-Pool" })).toBeVisible();
  });

  test("ZoneHealthBadge in Status-Spalte (nur fuer zugewiesene Geraete)", async ({ page }) => {
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([ASSIGNED_DEVICE, POOL_DEVICE]),
      }),
    );
    await mockHardwareStatus(page);

    await page.goto("/devices");

    const badges = page.getByTestId("zone-health-badge");
    // Nur das zugewiesene Geraet hat eine Zone -> genau ein Badge, degraded.
    await expect(badges).toHaveCount(1);
    await expect(badges.first()).toHaveAttribute("data-health", "degraded");
    await expect(badges.first()).toContainText("Zone Achtung");
  });

  test("Empty-State bei leerer Liste", async ({ page }) => {
    await page.route("**/api/v1/devices*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.goto("/devices");
    await expect(page.getByText("Noch keine Geräte")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// /devices/[id]-Detail (2 Karten + 7 Kacheln, D5)
// ---------------------------------------------------------------------------

test.describe("Sprint 14a — /devices/[id]-Detail", () => {
  async function mockDetail(page: Page, device: { id: number } & Record<string, unknown>) {
    await page.route(`**/api/v1/devices/${device.id}`, (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(device),
      });
    });
    await page.route(`**/api/v1/devices/${device.id}/sensor-readings*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_READINGS),
      }),
    );
    await mockHardwareStatus(page);
  }

  test("Header, Zuordnungs-Karte, Identifikations-Karte", async ({ page }) => {
    await mockDetail(page, ASSIGNED_DEVICE);
    await page.goto("/devices/42");

    await expect(page.getByRole("heading", { name: "Vicki-Bad-102" })).toBeVisible();
    // Zuordnungs-Karte
    await expect(page.getByText("Doppelzimmer")).toBeVisible();
    await expect(page.getByText("Bad", { exact: true })).toBeVisible();
    // Identifikations-Karte
    const hwRow = page.getByTestId("hardware-number-row");
    await expect(hwRow).toContainText("MDC5419731K6UF");
    await expect(page.getByText("4.2")).toBeVisible(); // Firmware
    // Zone-Badge (detailed) im Header
    await expect(page.getByTestId("zone-health-badge")).toHaveAttribute("data-health", "degraded");
  });

  test("7 Kacheln inkl. Ventilstellung, Fenster+Backplate, Override", async ({ page }) => {
    await mockDetail(page, ASSIGNED_DEVICE);
    await page.goto("/devices/42");

    await expect(page.getByText("Temperatur").first()).toBeVisible();
    await expect(page.getByText("Sollwert").first()).toBeVisible();
    await expect(page.getByText("Batterie").first()).toBeVisible();
    await expect(page.getByText("Signal").first()).toBeVisible();
    // Ventilstellung: 42 % (im Range)
    await expect(page.getByTestId("kpi-ventilstellung")).toContainText("42 %");
    // Fenster zu, Montage montiert
    const wb = page.getByTestId("window-backplate-card");
    await expect(wb).toContainText("zu");
    await expect(wb).toContainText("montiert");
    // Override: keiner aktiv
    await expect(page.getByTestId("override-card")).toContainText("Kein Override aktiv");
  });

  test("Override-Kachel zeigt aktiven Override read-only", async ({ page }) => {
    const withOverride = {
      ...ASSIGNED_DEVICE,
      active_override: {
        source: "frontend_4h",
        setpoint_celsius: 21.5,
        started_at: iso(60 * 60 * 1000),
        expires_at: iso(-3 * 60 * 60 * 1000),
      },
    };
    await mockDetail(page, withOverride);
    await page.goto("/devices/42");

    const card = page.getByTestId("override-card");
    await expect(card).toContainText("Override aktiv");
    await expect(card).toContainText("21.5 °C");
    await expect(card).toContainText("Rezeption (4 h)");
  });

  test("Ventilstellung-Defensive: Out-of-Range -> nicht verfügbar", async ({ page }) => {
    const badValve = {
      ...ASSIGNED_DEVICE,
      latest_reading: { ...ASSIGNED_DEVICE.latest_reading, valve_position: 1984 },
    };
    await mockDetail(page, badValve);
    await page.goto("/devices/42");
    await expect(page.getByTestId("kpi-ventilstellung")).toContainText("nicht verfügbar");
  });

  test("404 bei unbekannter Device-ID", async ({ page }) => {
    await page.route("**/api/v1/devices/9999", (route) =>
      route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Device 9999 nicht gefunden" }),
      }),
    );
    await page.goto("/devices/9999");
    await expect(page.getByText("Gerät nicht gefunden")).toBeVisible();
  });

  test("Hardware-Nummer Inline-Edit: Happy-Path speichert + refetch", async ({ page }) => {
    let hwNumber: string | null = ASSIGNED_DEVICE.hardware_number;
    await page.route("**/api/v1/devices/42", async (route) => {
      const method = route.request().method();
      if (method === "PATCH") {
        const body = route.request().postDataJSON() as { hardware_number?: string | null };
        hwNumber = body.hardware_number ?? null;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...ASSIGNED_DEVICE, hardware_number: hwNumber }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...ASSIGNED_DEVICE, hardware_number: hwNumber }),
      });
    });
    await page.route("**/api/v1/devices/42/sensor-readings*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await mockHardwareStatus(page);

    await page.goto("/devices/42");
    await page.getByRole("button", { name: "Hardware-Nummer bearbeiten" }).click();
    const input = page.getByRole("textbox", { name: "Hardware-Nummer bearbeiten" });
    await input.fill("NEWHW-9999");
    await input.press("Enter");

    await expect(page.getByTestId("hardware-number-row")).toContainText("NEWHW-9999");
  });

  test("Hardware-Nummer Inline-Edit: 409-Konflikt zeigt Fehler, Edit bleibt offen", async ({
    page,
  }) => {
    await page.route("**/api/v1/devices/42", async (route) => {
      if (route.request().method() === "PATCH") {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Hardware-Nummer 'DUP-1' ist bereits vergeben",
            error_code: null,
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(ASSIGNED_DEVICE),
      });
    });
    await page.route("**/api/v1/devices/42/sensor-readings*", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await mockHardwareStatus(page);

    await page.goto("/devices/42");
    await page.getByRole("button", { name: "Hardware-Nummer bearbeiten" }).click();
    const input = page.getByRole("textbox", { name: "Hardware-Nummer bearbeiten" });
    await input.fill("DUP-1");
    await input.press("Enter");

    await expect(page.getByText(/bereits vergeben/)).toBeVisible();
    // Edit-Mode bleibt offen (Input weiter sichtbar).
    await expect(input).toBeVisible();
  });
});
