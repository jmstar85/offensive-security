/**
 * Playwright config for v4.0 P3-main e2e specs.
 *
 * Specs live in `e2e/`. Default browser is Chromium; tests assume the
 * frontend is reachable at http://localhost:5173 (vite dev server) and the
 * backend at http://localhost:8000 (uvicorn). Both are started by the
 * operator before `npm run e2e`.
 */
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: 'list',
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
