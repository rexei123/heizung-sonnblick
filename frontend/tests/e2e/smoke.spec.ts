import { test, expect, type Page, type Route } from './fixtures';

/**
 * Die beiden Seiten-Smokes brauchen seit dem Hotfix vom 16.10.2026 eine
 * **Sitzung**: eine geschuetzte Seite ohne Anmeldung leitet jetzt auf
 * `/login` um (vorher rendete sie ihr leeres Geruest).
 *
 * Diese Datei war die einzige, die ihren `test` noch direkt aus
 * `@playwright/test` bezogen hat — die Umstellung auf die gemeinsame
 * Huelle (Sprint 22 T8) hat sie uebersprungen, weil sie als einzige ein
 * **BOM** am Dateianfang trug und das Suchmuster deshalb nicht passte
 * (§5.3). Das BOM ist mit diesem Hotfix weg.
 *
 * Dass der erste Test „kein Redirect mehr" heisst, bleibt richtig: gemeint
 * war Sprint 14c, wo `/` keine Weiterleitung auf `/devices` mehr ist.
 * **Angemeldet** ist das Dashboard weiterhin unter `/` zu sehen, und genau
 * das prueft er — nur sagt er die Sitzung jetzt dazu.
 */
async function mockApi(page: Page): Promise<void> {
  await page.route('**/api/v1/**', (r: Route) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  );
}

test.describe('Smoke-Tests', () => {
  test('Startseite zeigt angemeldet das Dashboard (kein Redirect mehr)', async ({
    page,
  }) => {
    // Sprint 14c: page.tsx ist nicht mehr redirect("/devices"), sondern das
    // Dashboard mit Begruessung + KPI-Kacheln. URL bleibt "/".
    await mockApi(page);
    await page.goto('/');
    await expect(page).toHaveURL(/\/$/);
    await expect(
      page.getByRole('heading', { level: 1, name: /Guten (Morgen|Tag|Abend)|Hallo/ }),
    ).toBeVisible();
  });

  test('Startseite leitet abgemeldet auf die Anmeldung', async ({ page }) => {
    // Die Gegenrichtung desselben Smokes — der Befund vom 16.10.2026.
    await mockApi(page);
    await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
      r.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Nicht angemeldet' }),
      }),
    );
    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);
  });

  test('/devices liefert HTML mit Geraete-Liste', async ({ page }) => {
    await mockApi(page);
    const response = await page.goto('/devices');
    expect(response?.status()).toBe(200);
    // Nicht `body`: das wuerde auch die Anmeldeseite erfuellen. Die
    // Ueberschrift der Geraeteliste erfuellt nur die Geraeteliste.
    await expect(page.getByRole('heading', { level: 1, name: /Geräte/i })).toBeVisible();
  });

  test('GET /healthz liefert 200 und gueltiges JSON', async ({ request }) => {
    const res = await request.get('/healthz');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ ok: true, service: 'web' });
    expect(typeof body.ts).toBe('string');
    // ts ist ein parsbarer ISO-Timestamp
    expect(Number.isNaN(Date.parse(body.ts))).toBe(false);
  });
});
