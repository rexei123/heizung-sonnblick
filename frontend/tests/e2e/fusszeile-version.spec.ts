import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Die Fussleiste nennt die Version — und nicht die Stage (15.10.2026).
 *
 * Vorher stand dort `v0.1.x · Test-Stage`. Beides war falsch:
 *
 * 1. Die Zahl war seit Sprint 9 nicht nachgezogen (`0.1.x` als Platzhalter,
 *    nicht als Version).
 * 2. **„Test" liest das Personal als „das ist nicht das echte System".**
 *    Dieser Server *ist* die Produktion (AE-67, Promote am 09.06.2026);
 *    `STAGE=test` bleibt serverseitig stehen, weil Deploy-Pfade daran
 *    haengen, aber das ist eine Angabe für den Betrieb und keine für den
 *    Bildschirm.
 *
 * Der zweite Test ist der wichtigere: er faellt, sobald irgendwo in der
 * Fussleiste wieder ein „Test" oder „Stage" auftaucht. Die Version selbst
 * wird gegen `package.json` geprueft, nicht gegen eine hier notierte Zahl
 * — sonst waere der Test die dritte Wahrheit (§5.53).
 */

import pkg from "../../package.json";

async function mockApi(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
}

test.describe("Fussleiste", () => {
  test("zeigt die Version aus package.json", async ({ page }) => {
    await mockApi(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");

    await expect(page.getByText(`v${pkg.version}`, { exact: true })).toBeVisible();
  });

  test("nennt weder Test noch Stage", async ({ page }) => {
    await mockApi(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");

    // Der Anker: die Fussleiste ist da (sonst prüfte der Test ein leeres
    // Dokument und wäre auch grün, wenn die Seite gar nicht lädt).
    const zeile = page.getByText(`v${pkg.version}`, { exact: true });
    await expect(zeile).toBeVisible();

    const fuss = page.locator("div").filter({ has: zeile }).last();
    await expect(fuss).not.toContainText("Test");
    await expect(fuss).not.toContainText("Stage");
  });
});
