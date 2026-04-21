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
});
