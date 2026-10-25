import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// The lower third: a called moment over a playing video shows its clock, player, event and score for about
// 5 s, aria-hidden, inside the picture. A fake YouTube player stands in.

const KOBE = /^Basketball ?Kobe's 81/

test.use({ launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] } })

test('a called moment shows the lower third over the video, hidden from screen readers',async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()
  const l3 = page.getByTestId('lower-third')
  await expect(l3).toBeVisible({ timeout: 30_000 })
  await expect(l3).toHaveAttribute('aria-hidden', 'true')
  await expect(l3.locator('.l3-sub')).toContainText(/\d+–\d+/) // the score after the moment
  if (process.env.L3_SHOT) await page.locator('.vcard').screenshot({ path: process.env.L3_SHOT })
  // never over the caption card under the picture
  const [a, b] = [await l3.boundingBox(), await page.locator('.vcard .frame').boundingBox()]
  expect(a!.y + a!.height).toBeLessThanOrEqual(b!.y + b!.height)
})
