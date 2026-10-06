import { expect, test } from '@playwright/test'

test('the interface boots to sign-in', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/Lilly/)
  await expect(page.getByRole('heading', { name: 'Lilly' })).toBeVisible()
  await expect(page.getByLabel('Access token')).toBeVisible()
})
