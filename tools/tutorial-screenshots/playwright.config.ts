import { defineConfig } from '@playwright/test';

/**
 * Playwright config for the tutorial screenshot capture pipeline.
 *
 * This is a standalone toolkit — not part of the app's own test suite —
 * so it lives under tools/tutorial-screenshots with its own
 * package.json/node_modules rather than inside frontend/ or landing/.
 */
export default defineConfig({
  testDir: '.',
  testMatch: 'capture.spec.ts',
  timeout: 60_000,
  retries: 1,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.APP_BASE_URL || 'http://localhost:3000',
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  },
});
