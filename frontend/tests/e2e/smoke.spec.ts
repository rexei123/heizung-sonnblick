import { test, expect } from '@playwright/test';

test.describe('Smoke-Tests', () => {
  test('Startseite antwortet und liefert HTML', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle(/Sonnblick|Heizung|Next/i);
  });

  test('Startseite enthaelt main-Element', async ({ page }) => {
    await page.goto('/');
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
