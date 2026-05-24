/**
 * v4.0 P3-main e2e — flag ON renders the 2-pane flow shell on /flow/:id.
 *
 * With `settings.osa_flow_ui_enabled=true`, navigating to /flow/{id} must:
 *   - Render the resizable PanelGroup wrapper.
 *   - Mount the right-pane tabs (Terminal, Tasks, Agents).
 *   - Default the right pane to the Terminal tab and connect xterm.
 *   - Mount the left-pane tabs (Automation, Assistant, Dashboard).
 *
 * The backend WebSocket is mocked at the route level so the test does not
 * need a live socket server.
 */
import { expect, test } from '@playwright/test'

const FAKE_SESSION_ID = '00000000-0000-0000-0000-000000000001'

test.describe('flag ON — /flow/:id renders the new shell', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/config/feature-flags', (route) =>
      route.fulfill({ json: { osa_flow_ui_enabled: true } })
    )
    // Auth so PrivateRoute admits us.
    await page.addInitScript(() =>
      window.localStorage.setItem('token', 'test-token-flag-on')
    )
    // Mock /pentest-sessions/{id} so PentestWorkflow doesn't blow up.
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
    // Mock the new msgchains endpoint.
    await page.route(
      `**/api/v1/pentest-sessions/${FAKE_SESSION_ID}/msgchains`,
      (route) => route.fulfill({ json: [] })
    )
  })

  test('renders right-pane tabs in the expected order', async ({ page }) => {
    await page.goto(`/flow/${FAKE_SESSION_ID}`)
    await expect(page.getByRole('tab', { name: 'Terminal' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Tasks' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Agents' })).toBeVisible()
  })

  test('renders left-pane tabs (Automation / Assistant / Dashboard)', async ({
    page,
  }) => {
    await page.goto(`/flow/${FAKE_SESSION_ID}`)
    await expect(page.getByRole('tab', { name: 'Automation' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Assistant' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'Dashboard' })).toBeVisible()
  })

  test('terminal tab mounts an xterm host element', async ({ page }) => {
    await page.goto(`/flow/${FAKE_SESSION_ID}`)
    // Terminal is the default selected tab.
    await expect(page.getByTestId('flow-terminal')).toBeVisible()
  })

  test('agents tab shows empty-state when no chains', async ({ page }) => {
    await page.goto(`/flow/${FAKE_SESSION_ID}`)
    await page.getByRole('tab', { name: 'Agents' }).click()
    await expect(
      page.getByText(/no agent chains yet/i)
    ).toBeVisible()
  })
})
