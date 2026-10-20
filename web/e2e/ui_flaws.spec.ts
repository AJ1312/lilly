import { expect, test } from '@playwright/test'

test.describe('Comprehensive UI/UX Flow & Flaw Detection', () => {
  test('all primary navigation routes load cleanly without console errors or layout crashes', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text())
      }
    })

    await page.goto('/')

    const navItems = [
      { name: 'Talk & Assist', selector: '.chat-input-pill' },
      { name: 'Workspace', selector: '.workspace-layout' },
      { name: 'Agents', selector: 'h1:has-text("Specialist Agents")' },
      { name: 'Skills', selector: 'h1:has-text("Skills Catalog")' },
      { name: 'Models', selector: 'h1:has-text("Models & Catalog")' },
      { name: 'Routines', selector: 'h1:has-text("Routines & Playbooks")' },
      { name: 'Memory', selector: 'h1:has-text("Memory Bank")' },
      { name: 'Notes', selector: 'h1:has-text("Spaces & Notes")' },
      { name: 'Approvals', selector: 'h1:has-text("Security Approvals")' },
      { name: 'Activity', selector: 'h1:has-text("Activity & Decision Log")' },
      { name: 'Resources', selector: 'h1:has-text("System Resources & Telemetry")' },
      { name: 'Settings', selector: 'h1:has-text("Settings & Configuration")' },
    ]

    for (const item of navItems) {
      const btn = page.getByRole('button', { name: item.name, exact: true })
      await expect(btn).toBeVisible()
      await btn.click()
      await expect(page.locator(item.selector)).toBeVisible({ timeout: 5000 })
    }

    // Filter out expected network fetch failures when backend is mock/unreachable in e2e
    const realErrors = consoleErrors.filter(
      (err) =>
        !err.includes('Failed to load resource') &&
        !err.includes('net::ERR_CONNECTION_REFUSED') &&
        !err.includes('404') &&
        !err.includes('500')
    )
    expect(realErrors).toEqual([])
  })

  test('talk view file attachment chips work and allow removal', async ({ page }) => {
    await page.goto('/')

    // Locate file input and set a file
    const fileInput = page.locator('input[type="file"]')
    await expect(fileInput).toHaveCount(1)

    await fileInput.setInputFiles({
      name: 'test_document.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Sample test content for attachment check'),
    })

    // Check attachment chip renders above chat input
    const chip = page.locator('.attachment-chip')
    await expect(chip).toBeVisible()
    await expect(chip).toContainText('test_document.txt')

    // Click remove button on chip
    const removeBtn = chip.locator('button')
    await removeBtn.click()
    await expect(chip).not.toBeVisible()
  })

  test('talk view autonomy dropdown switches between Auto, Approve, and Off', async ({ page }) => {
    await page.goto('/')

    const pillSelect = page.locator('.chat-input-pill select')
    await expect(pillSelect).toBeVisible()

    // Select AUTO
    await pillSelect.selectOption('AUTO')
    await expect(pillSelect).toHaveValue('AUTO')

    // Change to MANUAL (Approve)
    await pillSelect.selectOption('MANUAL')
    await expect(pillSelect).toHaveValue('MANUAL')

    // Change to OFF
    await pillSelect.selectOption('OFF')
    await expect(pillSelect).toHaveValue('OFF')
  })

  test('settings tabs all switch seamlessly and render controls', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Settings & Configuration' })).toBeVisible()

    const tabs = [
      'General & Safety',
      'Engine & Execution',
      'Limits & Capacity',
      'Grounding & Guardrails',
      'Network & Search',
      'Laya Voice',
      'DevBox Sandbox',
      'MCP Servers',
      'Data & Maintenance',
    ]

    for (const tabName of tabs) {
      const tabBtn = page.getByRole('button', { name: tabName })
      await expect(tabBtn).toBeVisible()
      await tabBtn.click()
      // ensure active state
      await expect(tabBtn).toHaveClass(/active/)
    }
  })

  test('theme toggle switches theme and persists attribute', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()

    // Click Light Theme button
    const lightBtn = page.getByRole('button', { name: 'light Theme' })
    await lightBtn.click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

    // Click Dark Theme button
    const darkBtn = page.getByRole('button', { name: 'dark Theme' })
    await darkBtn.click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })
})
