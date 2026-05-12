import { test, expect, type Route } from "@playwright/test";

/**
 * Sprint 9.13a — Geraete-Pairing-Wizard + Detach-Button.
 *
 * Backend gemockt via page.route, analog devices.spec.ts (Sprint 7).
 */

const NOW = Date.now();

const VICKI_UNASSIGNED = {
  id: 11,
  dev_eui: "0011223344556677",
  app_eui: null,
  kind: "thermostat",
  vendor: "mclimate",
  model: "Vicki",
  label: null,
  heating_zone_id: null,
  is_active: true,
  last_seen_at: new Date(NOW - 5 * 60 * 1000).toISOString(),
  created_at: new Date(NOW - 86400 * 1000).toISOString(),
  updated_at: new Date(NOW).toISOString(),
};

const VICKI_ASSIGNED = {
  ...VICKI_UNASSIGNED,
  id: 12,
  dev_eui: "0011223344556678",
  label: "Vicki-001",
  heating_zone_id: 91,
};

const ROOM_101 = {
  id: 101,
  number: "101",
  display_name: "Doppelzimmer Süd",
  room_type_id: 1,
  floor: 1,
  orientation: "S",
  status: "vacant",
  notes: null,
  created_at: new Date(NOW - 86400 * 1000).toISOString(),
  updated_at: new Date(NOW).toISOString(),
};

const HEATING_ZONE_91 = {
  id: 91,
  room_id: 101,
  kind: "bedroom",
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: new Date(NOW - 86400 * 1000).toISOString(),
  updated_at: new Date(NOW).toISOString(),
};

function mockJson(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

test.describe("Sprint 9.13a Pairing-Wizard", () => {
  test("/devices zeigt CTA „Gerät hinzufügen“ und führt zum Wizard", async ({
    page,
  }) => {
    await page.route("**/api/v1/devices*", (r) => mockJson(r, [VICKI_ASSIGNED]));
    // RoomStep + HeatingZoneStep nicht zwingend für Step 1, aber Page lädt useRooms
    // beim Mount — Mock vorhalten verhindert XHR-Fehler im Test-Run.
    await page.route("**/api/v1/rooms*", (r) => mockJson(r, [ROOM_101]));

    await page.goto("/devices");

    const cta = page.getByRole("link", { name: /Gerät hinzufügen/i });
    await expect(cta).toBeVisible();

    await cta.click();
    await expect(page).toHaveURL(/\/devices\/pair$/);
    await expect(
      page.getByRole("heading", { name: "Gerät hinzufügen" }),
    ).toBeVisible();
  });

  test("Wizard zeigt 4 Stepper-Einträge", async ({ page }) => {
    await page.route("**/api/v1/devices*", (r) => mockJson(r, [VICKI_UNASSIGNED]));
    await page.route("**/api/v1/rooms*", (r) => mockJson(r, [ROOM_101]));

    await page.goto("/devices/pair");

    const stepper = page.getByRole("list", { name: /Wizard-Schritte/ });
    await expect(stepper).toBeVisible();
    await expect(stepper.getByText("Gerät", { exact: true })).toBeVisible();
    await expect(stepper.getByText("Zimmer", { exact: true })).toBeVisible();
    await expect(stepper.getByText("Heizzone", { exact: true })).toBeVisible();
    await expect(stepper.getByText("Label & Bestätigen")).toBeVisible();
  });

  test('„Weiter" disabled solange kein Gerät gewählt', async ({ page }) => {
    await page.route("**/api/v1/devices*", (r) => mockJson(r, [VICKI_UNASSIGNED]));
    await page.route("**/api/v1/rooms*", (r) => mockJson(r, [ROOM_101]));

    await page.goto("/devices/pair");

    const next = page.getByRole("button", { name: /^Weiter$/ });
    await expect(next).toBeDisabled();
  });

  test("Step 1 zeigt unzugeordnete Geräte aus der Liste", async ({ page }) => {
    await page.route("**/api/v1/devices*", (r) =>
      mockJson(r, [VICKI_UNASSIGNED, VICKI_ASSIGNED]),
    );
    await page.route("**/api/v1/rooms*", (r) => mockJson(r, [ROOM_101]));

    await page.goto("/devices/pair");

    // 1 unzugeordnetes Gerät erwartet (VICKI_ASSIGNED hat heating_zone_id != null)
    await expect(page.getByText(/1 Gerät\(e\) noch keiner Heizzone/)).toBeVisible();
  });

  test("Detach-ConfirmDialog auf /zimmer/[id] erscheint korrekt", async ({
    page,
  }) => {
    await page.route("**/api/v1/rooms/101", (r) => mockJson(r, ROOM_101));
    await page.route("**/api/v1/rooms/101/heating-zones", (r) =>
      mockJson(r, [HEATING_ZONE_91]),
    );
    await page.route("**/api/v1/devices*", (r) => mockJson(r, [VICKI_ASSIGNED]));

    await page.goto("/zimmer/101");

    // Auf den Geräte-Tab wechseln
    await page.getByRole("button", { name: "Geräte" }).click();

    // Trennen-Button sichtbar pro Gerät
    const detachBtn = page.getByRole("button", {
      name: /Gerät von Heizzone trennen/,
    });
    await expect(detachBtn).toBeVisible();

    await detachBtn.click();

    await expect(
      page.getByRole("alertdialog", { name: /Gerät von Heizzone trennen/ }),
    ).toBeVisible();
    await expect(page.getByText(/„Vicki-001"/)).toBeVisible();
    await expect(page.getByText(/„Schlafzimmer"/)).toBeVisible();
  });

  test("Inline-Edit-Input hat autoComplete=off und zeigt aktuellen Label-Wert (HF-9.13a-1)", async ({
    page,
  }) => {
    await page.route("**/api/v1/devices*", (r) => mockJson(r, [VICKI_ASSIGNED]));
    await page.route("**/api/v1/rooms*", (r) => mockJson(r, [ROOM_101]));

    await page.goto("/devices");

    // Edit-Pencil neben dem Label öffnen
    await page.getByRole("button", { name: "Bezeichnung bearbeiten" }).first().click();

    const input = page.getByRole("textbox", { name: "Bezeichnung bearbeiten" });
    await expect(input).toBeVisible();
    // Hardening gegen Browser-Autofill (B-LT-1 Hypothese b)
    await expect(input).toHaveAttribute("autocomplete", "off");
    // Input zeigt aktuellen Label-Wert beim Edit-Click (B-9.13a-2)
    await expect(input).toHaveValue("Vicki-001");
  });
});
