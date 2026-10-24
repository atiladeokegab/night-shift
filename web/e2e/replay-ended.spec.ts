import { expect, test } from '@playwright/test'

// A replay the server has dropped (#454): its 404 "no replay" on Ask ends it on the page, with a way to
// start it again, instead of an answer that never comes.
test('a dropped replay says it has ended and starts again', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /^Football ?Battle of the Bridge/ }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await page.route('**/replays/*/ask', (r) => r.fulfill({ status: 404, json: { detail: "no replay 'gone'" } }))
  await page.locator('textarea').first().fill("What's the score?")
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const alert = page.getByRole('alert').filter({ hasText: 'This replay has ended' })
  await expect(alert).toBeVisible()
  await page.unroute('**/replays/*/ask')
  const restarted = page.waitForRequest((r) => r.method() === 'POST' && new URL(r.url()).pathname === '/replays')
  await alert.getByRole('button', { name: 'Start again' }).click()
  await restarted
  await expect(alert).toHaveCount(0)
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
})
