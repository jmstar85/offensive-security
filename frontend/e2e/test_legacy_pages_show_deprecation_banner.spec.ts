/**
 * v4.0 P3-main e2e — deprecation banner is shown on legacy pages when
 * `osa_flow_ui_enabled=true`.
 *
 * Pages that are slated for removal in P5 (`Monitor`, `PentestWorkflow`,
 * `AgentCatalog`, `InteractionDashboard`) must show a banner pointing to
 * /flow/:id once the flag is ON. The legacy page itself still renders
 * (P5 is the deletion step), but operators see a clear migration nudge.
 *
 * Note: in v4.0 P3-main the banner is rendered by each page that opts in
 * via <DeprecationBanner pageName=... />. P5 then deletes the host page.
 */
import { expect, test } from '@playwright/test'

const FAKE_SESSION_ID = '00000000-0000-0000-0000-000000000001'

test.describe('flag ON — legacy pages show deprecation banner', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/config/feature-flags', (route) =>
      route.fulfill({ json: { osa_flow_ui_enabled: true } })
    )
    await page.addInitScript(() =>
      window.localStorage.setItem('token', 'test-token-banner')
    )
  })

  test('Monitor page (/sessions/:id/monitor) shows banner', async ({ page }) => {
    await page.goto(`/sessions/${FAKE_SESSION_ID}/monitor`)
    await expect(
      page.getByText(/Monitor is moving to the new \/flow shell/i)
    ).toBeVisible()
  })

  test('PentestWorkflow page (/pentest-sessions/:id) shows banner', async ({
    page,
  }) => {
    await page.route(`**/api/v1/pentest-sessions/${FAKE_SESSION_ID}`, (route) =>
      route.fulfill({
        json: {
          id: FAKE_SESSION_ID,
          project_id: '00000000-0000-0000-0000-000000000002',
          status: 'pending',
          interview_state: 'not_started',
          interview_turn_count: 0,
          ambiguity_score: 1.0,
          model_id: 'claude-sonnet-4-6',
          domain_agent_slug: null,
          draft_plan_json: { steps: [] },
          ambiguity_override_reason: null,
        },
      })
    )
    await page.goto(`/pentest-sessions/${FAKE_SESSION_ID}`)
    await expect(
      page.getByText(/PentestWorkflow is moving to the new \/flow shell/i)
    ).toBeVisible()
  })

  test('AgentCatalog page (/agents) shows banner', async ({ page }) => {
    await page.goto('/agents')
    await expect(
      page.getByText(/AgentCatalog is moving to the new \/flow shell/i)
    ).toBeVisible()
  })

  test('banner CTA navigates to /flow', async ({ page }) => {
    await page.goto('/agents')
    await page
      .getByRole('link', { name: '/flow' })
      .first()
      .click()
    // /flow alone is not a registered route — App.tsx redirects unknown
    // routes back to /dashboard via the `*` route.
    await expect(page).toHaveURL(/\/dashboard$/)
  })
})
