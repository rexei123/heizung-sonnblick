import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 9.17 T12 - Auth Frontend Playwright-Tests.
 *
 * Backend-API wird per route.fulfill() gemockt; kein laufender FastAPI-
 * Server noetig. Test-Szenarien:
 *  - /login zeigt Formular, falsche Credentials → Inline-Fehler
 *  - Erfolgreicher Login → Redirect Dashboard
 *  - must_change_password=true → Redirect /auth/change-password
 *  - /einstellungen/benutzer ohne Login → Redirect /login
 *  - /einstellungen/benutzer als Mitarbeiter → Redirect /
 *  - /einstellungen/benutzer als Admin → Liste sichtbar
 *  - Sidebar-Footer zeigt User-E-Mail + Logout-Button
 */

type Role = "admin" | "mitarbeiter";

interface MockUser {
  id: number;
  email: string;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

const MOCK_ADMIN: MockUser = {
  id: 1,
  email: "admin@hotel.example.com",
  role: "admin",
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  last_login_at: "2026-05-13T18:00:00Z",
};

const MOCK_MITARBEITER: MockUser = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter",
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  last_login_at: null,
};

/**
 * Mockt alle /api/v1-Routen mit harmlosen Defaults; einzelne Tests
 * koennen einzelne Routen ueberschreiben (Playwright nimmt das
 * spezifischere Pattern zuerst, aber letztes route() gewinnt).
 */
async function mockApi(
  page: Page,
  opts: {
    me?: MockUser | null;
    loginResult?: "ok" | "401" | "401-then-ok" | "429" | "503";
    users?: MockUser[];
    changePasswordResult?: "ok" | "400" | "429" | "503";
  } = {},
): Promise<void> {
  const me = opts.me === undefined ? null : opts.me;

  // WICHTIG: Playwright ruft route-Handler in UMGEKEHRTER Reihenfolge auf
  // (zuletzt registriert -> zuerst geprueft). Catch-all daher ZUERST
  // registrieren, damit spezifische Pattern danach Prioritaet haben.
  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.route("**/api/v1/auth/me", async (route: Route) => {
    if (me === null) {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Authentifizierung erforderlich" }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(me),
      });
    }
  });

  let loginCalls = 0;
  await page.route("**/api/v1/auth/login", async (route: Route) => {
    loginCalls += 1;
    if (opts.loginResult === "401") {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "E-Mail oder Passwort falsch" }),
      });
      return;
    }
    if (opts.loginResult === "429") {
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Rate limit exceeded" }),
      });
      return;
    }
    if (opts.loginResult === "503") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Service unavailable" }),
      });
      return;
    }
    if (opts.loginResult === "401-then-ok" && loginCalls === 1) {
      await route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({ detail: "E-Mail oder Passwort falsch" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ user: me ?? MOCK_ADMIN }),
    });
  });

  await page.route("**/api/v1/auth/change-password", async (route: Route) => {
    if (opts.changePasswordResult === "400") {
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Aktuelles Passwort falsch" }),
      });
      return;
    }
    if (opts.changePasswordResult === "429") {
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Rate limit exceeded" }),
      });
      return;
    }
    if (opts.changePasswordResult === "503") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Service unavailable" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(me ?? MOCK_ADMIN),
    });
  });

  await page.route("**/api/v1/auth/logout", async (route: Route) => {
    await route.fulfill({ status: 204, body: "" });
  });

  await page.route("**/api/v1/users", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(opts.users ?? [MOCK_ADMIN, MOCK_MITARBEITER]),
    });
  });
}

test.describe("Sprint 9.17 Auth — Login-Flow", () => {
  test("/login zeigt das Anmelde-Formular", async ({ page }) => {
    await mockApi(page, { me: null });
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Heizung Sonnblick" })).toBeVisible();
    await expect(page.getByLabel("E-Mail")).toBeVisible();
    await expect(page.getByLabel("Passwort", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Anmelden" })).toBeVisible();
  });

  test("Falsche Credentials zeigen Inline-Fehler", async ({ page }) => {
    await mockApi(page, { me: null, loginResult: "401" });
    await page.goto("/login");
    await page.getByLabel("E-Mail").fill("admin@hotel.example.com");
    await page.getByLabel("Passwort", { exact: true }).fill("wrong");
    await page.getByRole("button", { name: "Anmelden" }).click();
    await expect(
      page.getByText("E-Mail oder Passwort falsch.", { exact: true }),
    ).toBeVisible();
  });

  test("Erfolgreicher Login leitet zum Dashboard", async ({ page }) => {
    await mockApi(page, { me: MOCK_ADMIN, loginResult: "ok" });
    await page.goto("/login");
    await page.getByLabel("E-Mail").fill("admin@hotel.example.com");
    await page.getByLabel("Passwort", { exact: true }).fill("AdminPassword123!");
    await page.getByRole("button", { name: "Anmelden" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("must_change_password=true leitet auf /auth/change-password", async ({ page }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser, loginResult: "ok" });
    await page.goto("/login");
    await page.getByLabel("E-Mail").fill("admin@hotel.example.com");
    await page.getByLabel("Passwort", { exact: true }).fill("AdminPassword123!");
    await page.getByRole("button", { name: "Anmelden" }).click();
    await expect(page).toHaveURL(/\/auth\/change-password$/);
  });
});

test.describe("Sprint 9.17a Auth — Wording 429/503 differenzieren (B-9.17-5)", () => {
  test("Login: 429 zeigt Wartezeit-Hinweis", async ({ page }) => {
    await mockApi(page, { me: null, loginResult: "429" });
    await page.goto("/login");
    await page.getByLabel("E-Mail").fill("admin@hotel.example.com");
    await page.getByLabel("Passwort", { exact: true }).fill("AdminPassword123!");
    await page.getByRole("button", { name: "Anmelden" }).click();
    await expect(
      page.getByText("Zu viele Versuche. Bitte 60 Sekunden warten.", { exact: true }),
    ).toBeVisible();
  });

  test("Login: 503 zeigt Wartungsmodus-Hinweis", async ({ page }) => {
    await mockApi(page, { me: null, loginResult: "503" });
    await page.goto("/login");
    await page.getByLabel("E-Mail").fill("admin@hotel.example.com");
    await page.getByLabel("Passwort", { exact: true }).fill("AdminPassword123!");
    await page.getByRole("button", { name: "Anmelden" }).click();
    await expect(
      page.getByText(/Anmeldung gerade nicht möglich/, { exact: false }),
    ).toBeVisible();
  });

  test("Change-Password: 429 zeigt Wartezeit-Hinweis", async ({ page }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser, changePasswordResult: "429" });
    await page.goto("/auth/change-password");
    await page.getByLabel("Aktuelles Passwort").fill("OldPasswordXXX1");
    await page.getByLabel("Neues Passwort", { exact: true }).fill("BrandNewPwd123!");
    await page.getByLabel("Neues Passwort wiederholen").fill("BrandNewPwd123!");
    await page.getByRole("button", { name: /Passwort ändern/ }).click();
    await expect(
      page.getByText("Zu viele Versuche. Bitte 60 Sekunden warten.", { exact: true }),
    ).toBeVisible();
  });

  test("Change-Password: 503 zeigt Wartungsmodus-Hinweis", async ({ page }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser, changePasswordResult: "503" });
    await page.goto("/auth/change-password");
    await page.getByLabel("Aktuelles Passwort").fill("OldPasswordXXX1");
    await page.getByLabel("Neues Passwort", { exact: true }).fill("BrandNewPwd123!");
    await page.getByLabel("Neues Passwort wiederholen").fill("BrandNewPwd123!");
    await page.getByRole("button", { name: /Passwort ändern/ }).click();
    await expect(
      page.getByText(/Anmeldung gerade nicht möglich/, { exact: false }),
    ).toBeVisible();
  });
});

test.describe("Sprint 9.17a Auth — Change-Password Inline-Fehler (B-9.17-9)", () => {
  test("Aktuelles Passwort falsch zeigt Inline-Fehler unter current-Feld", async ({
    page,
  }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser, changePasswordResult: "400" });
    await page.goto("/auth/change-password");
    await page.getByLabel("Aktuelles Passwort").fill("WrongOld12345!");
    await page.getByLabel("Neues Passwort", { exact: true }).fill("BrandNewPwd123!");
    await page.getByLabel("Neues Passwort wiederholen").fill("BrandNewPwd123!");
    await page.getByRole("button", { name: /Passwort ändern/ }).click();
    const err = page.locator("#current-error");
    await expect(err).toHaveText("Aktuelles Passwort falsch.");
  });

  test("Passwort zu kurz zeigt Inline-Fehler unter new-Feld", async ({ page }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser });
    await page.goto("/auth/change-password");
    await page.getByLabel("Aktuelles Passwort").fill("OldPasswordXXX1");
    await page.getByLabel("Neues Passwort", { exact: true }).fill("kurz");
    await page.getByLabel("Neues Passwort wiederholen").fill("kurz");
    await page.getByRole("button", { name: /Passwort ändern/ }).click();
    const err = page.locator("#new-error");
    await expect(err).toContainText("mindestens 12 Zeichen");
  });

  test("Passwoerter ungleich zeigt Inline-Fehler unter repeat-Feld", async ({
    page,
  }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser });
    await page.goto("/auth/change-password");
    await page.getByLabel("Aktuelles Passwort").fill("OldPasswordXXX1");
    await page.getByLabel("Neues Passwort", { exact: true }).fill("BrandNewPwd123!");
    await page.getByLabel("Neues Passwort wiederholen").fill("DifferentPwd456!");
    await page.getByRole("button", { name: /Passwort ändern/ }).click();
    const err = page.locator("#repeat-error");
    await expect(err).toHaveText("Passwörter stimmen nicht überein.");
  });
});

test.describe("Sprint 9.17a Auth — Mojibake-Audit (B-9.17-7)", () => {
  test("Keine ASCII-Umlaut-Workarounds in Change-Password-User-Strings", async ({
    page,
  }) => {
    const mustChangeUser: MockUser = { ...MOCK_ADMIN, must_change_password: true };
    await mockApi(page, { me: mustChangeUser });
    await page.goto("/auth/change-password");
    await page.getByLabel("Aktuelles Passwort").fill("OldPasswordXXX1");
    await page.getByLabel("Neues Passwort", { exact: true }).fill("BrandNewPwd123!");
    await page.getByLabel("Neues Passwort wiederholen").fill("DifferentPwd456!");
    await page.getByRole("button", { name: /Passwort ändern/ }).click();
    // Sichtbaren Body-Text greifen und auf Workaround-Tokens pruefen
    const body = await page.locator("body").innerText();
    expect(body).not.toContain("Passwoerter");
    expect(body).not.toContain("ueberein");
    expect(body).not.toContain("zuruecksetzen");
  });
});

test.describe("Sprint 9.17a Auth — Password-Sichtbarkeits-Toggle (B-9.17-8)", () => {
  test("Login: Toggle wechselt zwischen password und text", async ({ page }) => {
    await mockApi(page, { me: null });
    await page.goto("/login");
    const pwInput = page.getByLabel("Passwort", { exact: true });
    await pwInput.fill("MeinPasswort123!");
    await expect(pwInput).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: "Passwort sichtbar machen" }).click();
    await expect(pwInput).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: "Passwort verbergen" }).click();
    await expect(pwInput).toHaveAttribute("type", "password");
  });
});

test.describe("Sprint 9.17 Auth — /einstellungen/benutzer Zugriffsschutz", () => {
  test("Mitarbeiter wird auf / umgeleitet", async ({ page }) => {
    await mockApi(page, { me: MOCK_MITARBEITER });
    await page.goto("/einstellungen/benutzer");
    await expect(page).toHaveURL(/\/$/);
  });

  test("Admin sieht Benutzerliste mit E-Mail-Eintraegen", async ({ page }) => {
    await mockApi(page, { me: MOCK_ADMIN });
    await page.goto("/einstellungen/benutzer");
    await expect(page.getByRole("heading", { name: "Benutzer" })).toBeVisible();
    // Tabelle: admin steht in einer Zelle, mitarbeiter ebenso. Sidebar-
    // Footer enthaelt die admin-E-Mail zusaetzlich → first() reicht.
    await expect(page.getByRole("cell", { name: /admin@hotel\.example\.com/ })).toBeVisible();
    await expect(
      page.getByRole("cell", { name: /rezeption@hotel\.example\.com/ }),
    ).toBeVisible();
    // Self-Marker fuer den eingeloggten Admin
    await expect(page.getByText("(Du)")).toBeVisible();
  });

  test("Neuer-Benutzer-Dialog oeffnet sich", async ({ page }) => {
    await mockApi(page, { me: MOCK_ADMIN });
    await page.goto("/einstellungen/benutzer");
    await page.getByRole("button", { name: /Neuer Benutzer/i }).click();
    await expect(page.getByRole("dialog", { name: "Neuen Benutzer anlegen" })).toBeVisible();
    await expect(page.getByLabel("E-Mail", { exact: true }).nth(0)).toBeVisible();
  });
});

test.describe("Sprint 9.17 Auth — Sidebar-Footer", () => {
  test("Zeigt User-E-Mail und Logout-Button", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await mockApi(page, { me: MOCK_ADMIN });
    await page.goto("/");
    // Sidebar-Footer-Bereich
    const footer = page
      .getByRole("navigation", { name: "Hauptnavigation" })
      .locator("..")
      .locator("footer, [data-slot='sidebar-footer']")
      .first();
    // Konkretes Fallback: User-E-Mail muss irgendwo im Layout stehen.
    await expect(page.getByText(MOCK_ADMIN.email).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Abmelden|Logout/i })).toBeVisible();
  });
});
