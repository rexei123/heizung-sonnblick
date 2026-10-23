import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Fix A (20.10.2026) — Übersteuerung: zwei Dauern, ehrliche Historie.
 *
 * Entscheidung des Betreibers vom 19.10.2026:
 *
 * - Gast-Override (Drehknopf) gilt 24 h, jedes Drehen beginnt neu.
 * - Mitarbeiter-Auswahl: **nur** „24 Stunden" oder „Bis Check-out".
 *   Keine 4-Stunden-Regel, keine Nacht-Sonderregel.
 * - Die Sperre in freien Zimmern bleibt, wie sie ist.
 *
 * `frontend_4h` und `frontend_midnight` bleiben als **Werte** erhalten — die
 * Historie braucht ihre Etiketten —, sind aber nicht mehr wählbar.
 *
 * **Die Historie-Prüfung ist der zweite Teil und hat ihren eigenen Befund:**
 * bis zum 19.10. zeigte jeder abgelaufene Override „manuell aufgehoben",
 * weil die Anzeige nur auf `revoked_at` sah. Der Aufräum-Task und der
 * Check-out-Haken setzen beide `revoked_at` — mit einem Grund, der mit
 * „auto" beginnt. Für den **Normalfall** stand damit die falsche Aussage da.
 */

const MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-20T06:00:00Z",
  last_login_at: "2026-10-20T06:00:00Z",
};

const ROOM = {
  id: 101,
  number: "101",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "occupied",
  notes: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-20T06:00:00Z",
};

const ZONE = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

/** Eine Historie-Zeile. `revoked_reason` entscheidet über den Status-Text. */
function historie(
  id: number,
  source: string,
  revoked_at: string | null,
  revoked_reason: string | null,
): Record<string, unknown> {
  return {
    id,
    room_id: 101,
    heating_zone_id: 201,
    setpoint: "23.0",
    source,
    expires_at: "2026-10-19T09:00:00Z",
    reason: null,
    created_at: "2026-10-18T09:00:00Z",
    created_by: null,
    revoked_at,
    revoked_reason,
  };
}

async function mockRoom(page: Page, overrides: unknown[] = []): Promise<void> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/auth/me", (r: Route) => json(r, MITARBEITER));
  await page.route("**/api/v1/rooms/101", (r: Route) => json(r, ROOM));
  await page.route("**/api/v1/rooms/101/heating-zones", (r: Route) => json(r, [ZONE]));
  await page.route("**/api/v1/rooms/101/engine-trace*", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, (r: Route) =>
    json(r, overrides),
  );
}

/** Zimmerseite öffnen und auf den Reiter „Übersteuerung" wechseln. */
async function zumReiter(page: Page): Promise<void> {
  await page.goto("/zimmer/101");
  await page.getByRole("button", { name: "Übersteuerung", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Schlafzimmer" })).toBeVisible();
}

test.describe("Fix A — Übersteuerung", () => {
  test("auswahl_hat_nur_noch_zwei_dauern", async ({ page }) => {
    await mockRoom(page);
    await zumReiter(page);

    // Das Auswahlfeld öffnen und seine Einträge zählen.
    const auswahl = page.getByRole("combobox").first();
    await auswahl.click();

    await expect(page.getByRole("option", { name: /24 Stunden/ })).toBeVisible();
    await expect(page.getByRole("option", { name: /Bis Check-out/ })).toBeVisible();
    await expect(page.getByRole("option")).toHaveCount(2);

    // Die beiden alten Dauern dürfen nicht mehr wählbar sein.
    //
    // `/^4 Stunden/` ist verankert, und das ist nötig: ohne Anker passt die
    // Regex auch auf „**24** Stunden" und der Test schlägt an der richtigen
    // Oberfläche fehl. Beim ersten Lauf hat er genau das getan.
    await expect(page.getByRole("option", { name: /^4 Stunden/ })).toHaveCount(0);
    await expect(page.getByRole("option", { name: /Mitternacht/ })).toHaveCount(0);
  });

  test("abgelaufener_override_heisst_abgelaufen_nicht_aufgehoben", async ({ page }) => {
    // Drei Zeilen, drei Wege aus dem Leben eines Overrides.
    await mockRoom(page, [
      historie(1, "frontend_24h", "2026-10-19T09:00:00Z", "auto: expired"),
      historie(2, "device_manual", "2026-10-19T11:00:00Z", "auto_revoke_on_checkout"),
      historie(3, "frontend_checkout", "2026-10-19T12:00:00Z", "Gast hat sich beschwert"),
    ]);
    await zumReiter(page);

    await expect(page.getByText("abgelaufen", { exact: true })).toHaveCount(1);
    await expect(page.getByText("mit der Abreise beendet")).toHaveCount(1);
    await expect(page.getByText("manuell aufgehoben")).toHaveCount(1);
  });

  test("historische_quellen_bleiben_lesbar", async ({ page }) => {
    // Eine Bestandszeile von vor Fix A. Sie muss ihr Etikett behalten —
    // sonst wäre die Historie nach der Umstellung stumm.
    await mockRoom(page, [historie(4, "frontend_4h", "2026-10-18T13:00:00Z", "auto: expired")]);
    await zumReiter(page);

    await expect(page.getByText(/4 Stunden \(Mitarbeiter, alt\)/)).toBeVisible();
  });
});
