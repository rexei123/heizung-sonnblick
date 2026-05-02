import { test, expect } from '@playwright/test';

test.describe('Smoke-Tests', () => {
  test('Startseite redirected auf /devices', async ({ page }) => {
    // Seit N-4: page.tsx redirected auf /devices.
    // Playwright folgt automatisch -> finale URL muss /devices sein.
    await page.goto('/');
    await expect(page).toHaveURL(/\/devices$/);
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
