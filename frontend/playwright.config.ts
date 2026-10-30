import { defineConfig, devices } from '@playwright/test';

import { pruefeProxyZiel } from './tests/proxy-ziel';

/**
 * Playwright-Konfiguration Heizungssteuerung Hotel Sonnblick
 * Doku: https://playwright.dev/docs/test-configuration
 */
const isCI = !!process.env.CI;
const PORT = process.env.PORT ?? '3000';
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`;

/**
 * Schranke gegen ungemockte Anfragen an die Produktion. Sie läuft hier im
 * Modul-Rumpf, also bevor Playwright den `webServer` startet; die
 * Begründung samt Anlass steht in `tests/proxy-ziel.ts`. Der geprüfte
 * Wert geht unten an `webServer.env`, damit der Next-Prozess genau das
 * Ziel benutzt, das hier geprüft wurde.
 */
const PROXY_ZIEL = pruefeProxyZiel(__dirname);

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 1 : undefined,
  reporter: isCI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: 'npm run build && npm run start',
        url: BASE_URL,
        timeout: 120_000,
        reuseExistingServer: !isCI,
        env: { API_PROXY_TARGET: PROXY_ZIEL },
      },
});
