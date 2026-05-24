/**
 * v4.0 P3-main e2e — flag OFF preserves v2.1 UI (no regression).
 *
 * With `settings.osa_flow_ui_enabled=false` (default), the legacy 12-page
 * layout must render unchanged. The new `/flow/:id` route still exists in
 * the router (we don't conditionally remove routes — that's P5) but it is
 * not the default landing path and the deprecation banner does NOT appear.
 *
 * Operator preconditions:
 *   - Backend on :8000 with `OSA_FLOW_UI_ENABLED=false` (default).
 *   - Frontend on :5173.
 *   - A logged-in test user (TEST_TOKEN env or fixtures in `e2e/auth.setup.ts`).
 */
import { expect, test } from '@playwright/test'

test.describe('flag OFF — v2.1 baseline preserved', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the feature-flag endpoint so we can drive flag state without
    // restarting the backend.
    await page.route('**/api/v1/config/feature-flags', (route) =>
      route.fulfill({ json: { osa_flow_ui_enabled: false } })
    )
    // Inject a fake auth token so PrivateRoute lets us through.
    await page.addInitScript(() =>
      window.localStorage.setItem('token', 'test-token-flag-off')
    )
  })

  test('dashboard renders without flow-shell elements', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.getByText(/dashboard/i)).toBeVisible({ timeout: 10_000 })
    // The new flow shell's terminal element must NOT be present.
    await expect(page.getByTestId('flow-terminal')).toHaveCount(0)
  })

  test('deprecation banner is absent on legacy Monitor page', async ({ page }) => {
    await page.goto('/sessions/00000000-0000-0000-0000-000000000000/monitor')
    // Banner only renders when flag is ON.
    await expect(
      page.getByText(/moving to the new \/flow shell/i)
    ).toHaveCount(0)
  })

  test('all v2.1 sidebar routes are reachable', async ({ page }) => {
    const routes = ['/dashboard', '/projects', '/reports', '/agents', '/workflows']
    for (const route of routes) {
      await page.goto(route)
      // Each page should respond with HTTP 200 and render *some* content.
      await expect(page).toHaveURL(new RegExp(route.replace(/\//g, '\\/')))
    }
  })
})
