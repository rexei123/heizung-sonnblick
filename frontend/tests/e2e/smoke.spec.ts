import { test, expect } from '@playwright/test';

test.describe('Smoke-Tests', () => {
  test('Startseite zeigt das Dashboard (kein Redirect mehr)', async ({ page }) => {
    // Sprint 14c: page.tsx ist nicht mehr redirect("/devices"), sondern das
    // Dashboard mit Begruessung + KPI-Kacheln. URL bleibt "/".
    await page.goto('/');
    await expect(page).toHaveURL(/\/$/);
    await expect(
      page.getByRole('heading', { level: 1, name: /Guten (Morgen|Tag|Abend)|Hallo/ }),
    ).toBeVisible();
  });

  test('/devices liefert HTML mit Geraete-Liste', async ({ page }) => {
    const response = await page.goto('/devices');
    expect(response?.status()).toBe(200);
    const main = page.locator('main, [role="main"], body');
    await expect(main.first()).toBeVisible();
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
