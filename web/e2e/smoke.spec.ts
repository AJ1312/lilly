import { expect, test } from '@playwright/test'

test('the interface boots and displays navigation and talk composer', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/Lilly/)
  await expect(page.locator('aside.rail')).toBeVisible()
  await expect(page.getByText('Hey, Operator')).toBeVisible()

  // Chat input pill exists
  const chatPill = page.locator('.chat-input-pill')
  await expect(chatPill).toBeVisible()

  // Chat box strictly only has the autonomy dropdown (Auto / Approve / Off)
  const pillSelects = chatPill.locator('select')
  await expect(pillSelects).toHaveCount(1)
  const options = await pillSelects.locator('option').allTextContents()
  expect(options).toEqual(['Auto', 'Approve', 'Off'])

  // Paperclip file upload button exists
  const paperclip = chatPill.locator('button[title*="Attach"]')
  await expect(paperclip).toBeVisible()
})

test('options button toggles task parameters cleanly at top of view', async ({ page }) => {
  await page.goto('/')
  
  // Options button in hero greeting
  const optionsBtn = page.getByRole('button', { name: 'Options' })
  await expect(optionsBtn).toBeVisible()

  // Click Options to open parameters
  await optionsBtn.click()
  await expect(page.getByText('Target:')).toBeVisible()
  await expect(page.getByText('Specialist:')).toBeVisible()
  await expect(page.getByText('Intent:')).toBeVisible()
  await expect(page.getByText('Model:')).toBeVisible()
  await expect(page.getByText('Skill:')).toBeVisible()

  // Click again to close
  await optionsBtn.click()
  await expect(page.getByText('Specialist:')).not.toBeVisible()
})

test('navigation to settings, devbox tuning, and notes view', async ({ page }) => {
  await page.goto('/')

  // Navigate to Notes
  await page.getByRole('button', { name: 'Notes', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Spaces & Notes' })).toBeVisible()

  // Navigate to Settings
  await page.getByRole('button', { name: 'Settings' }).click()
  await expect(page.getByRole('heading', { name: 'Settings & Configuration' })).toBeVisible()

  // Check Freedom Mode buttons
  await expect(page.getByRole('heading', { name: 'Default Freedom Mode' })).toBeVisible()

  // Switch to DevBox tab
  await page.getByRole('button', { name: 'DevBox Sandbox' }).click()
  await expect(page.getByText('Container Resource & Timeout Tuning')).toBeVisible()

  // Switch to Data tab
  await page.getByRole('button', { name: 'Data & Maintenance' }).click()
  await expect(page.getByText('Session & Access Token Security')).toBeVisible()
})
