import { expect, test } from "@playwright/test";

/**
 * Sprint 8 Smoke-Tests fuer Stammdaten + Belegung-UI.
 *
 * Pruefen nur dass die Routen existieren und die Hauptueberschrift sichtbar ist.
 * CRUD-Tests gegen echte API folgen in Sprint 8.14 mit pytest-Integration-Suite
 * (H-4) — Playwright-E2E gegen Mock-DB ist fuer Sprint 8 zu invasiv.
 */

test.describe("Sprint 8 Stammdaten-UI", () => {
  test("/raumtypen rendert Master-Detail-Layout", async ({ page }) => {
    const res = await page.goto("/raumtypen");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Raumtypen" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Neuer Raumtyp/ })).toBeVisible();
  });

  test("/zimmer rendert Tabelle + Filter", async ({ page }) => {
    const res = await page.goto("/zimmer");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Zimmer" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Neues Zimmer/ })).toBeVisible();
  });

  test("/belegungen rendert Liste mit Range-Filter", async ({ page }) => {
    const res = await page.goto("/belegungen");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Belegungen" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Heute/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Naechste 7 Tage/ })).toBeVisible();
  });

  test("/einstellungen/hotel rendert 3 Cards", async ({ page }) => {
    const res = await page.goto("/einstellungen/hotel");
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Hotel-Stammdaten" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Allgemein" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Standardzeiten" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Alerts" })).toBeVisible();
  });

  test("AppShell-Sidebar enthaelt alle Sprint-8-Navigationspunkte", async ({ page }) => {
    await page.goto("/raumtypen");
    const nav = page.getByLabel("Hauptnavigation");
    for (const label of [
      "Übersicht",
      "Zimmer",
      "Belegungen",
      "Raumtypen",
      "Geräte",
      "Einstellungen",
    ]) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }
  });
});
