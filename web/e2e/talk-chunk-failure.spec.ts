import { expect, test } from '@playwright/test'

async function openDemo(page: import('@playwright/test').Page) {
  await page.goto('/?demo')
  await page.getByRole('button', { name: '▶ Hear a match called' }).click()
  await expect(page.locator('#ask-q')).toBeVisible()
}

test('a failed optional Talk chunk leaves the match and Ask available', async ({ page }) => {
  await page.addInitScript(() => {
    ;(window as unknown as { __unhandled: string[] }).__unhandled = []
    window.addEventListener('unhandledrejection', (event) => {
      ;(window as unknown as { __unhandled: string[] }).__unhandled.push(String(event.reason))
    })
  })
  let chunkRequests = 0
  await page.route('**/src/components/Converse.tsx', async (route) => {
    chunkRequests++
    await route.abort('failed')
  })

  await openDemo(page)
  await expect(page.getByRole('status').filter({ hasText: 'Talk is unavailable. Ask still works.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'About', exact: true })).toBeVisible()
  await expect(page.locator('#ask-q')).toBeEnabled()
  await expect.poll(() => chunkRequests).toBeGreaterThan(0)
  expect(await page.evaluate(() => (window as unknown as { __unhandled: string[] }).__unhandled)).toEqual([])
})

test('Talk still loads when its chunk is available', async ({ page }) => {
  await openDemo(page)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('#ask-q')).toBeEnabled()
})
