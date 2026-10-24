import { expect, test } from '@playwright/test'

// Post-deploy checks on the live site, public routes only (the ask is mocked in the browser).
test('#469 F1 has no Teams tab and T does nothing', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: /São Paulo/ }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await expect(page.getByRole('tab', { name: 'Teams' })).toHaveCount(0)
  await page.keyboard.press('t')
  await expect(page.getByRole('heading', { name: 'Teams', level: 2 })).toHaveCount(0)
})

test('#463 a dropped replay says it has ended', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /^Football ?Battle of the Bridge/ }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await page.route('**/replays/*/ask', (r) => r.fulfill({ status: 404, json: { detail: "no replay 'gone'" } }))
  await page.locator('textarea').first().fill("What's the score?")
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'This replay has ended' })).toBeVisible()
})
