import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// #462: the match wall (A-6.5), the home page, on the match server's real list. Every tile has a title
// and a call to action (no empty tiles, no loading ghosts left), and Tab moves through the tiles in order.

for (const width of [390, 1280]) {
  test(`the wall has no empty tiles and Tab moves through them at ${width}`, async ({ page }) => {
    await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
    await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')

    const tiles = page.locator('.wall button.tile')
    await expect(tiles.first()).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.wall .tile.ghost')).toHaveCount(0)
    const count = await tiles.count()
    expect(count).toBeGreaterThan(2)
    for (let i = 0; i < count; i++) {
      await expect(tiles.nth(i).locator('.tile-title')).not.toBeEmpty()
      await expect(tiles.nth(i).locator('.tile-cta')).not.toBeEmpty()
      const box = await tiles.nth(i).boundingBox()
      expect(box && box.width > 100 && box.height > 60, `tile ${i} has a size`).toBeTruthy()
    }

    // Tab from the top of the page: the tiles take focus in the order they are shown
    const reached: number[] = []
    for (let n = 0; n < 80 && reached.length < Math.min(count, 4); n++) {
      await page.keyboard.press('Tab')
      const at = await page.evaluate(() => {
        const all = [...document.querySelectorAll('.wall button.tile')]
        return all.indexOf(document.activeElement as Element)
      })
      if (at >= 0 && !reached.includes(at)) reached.push(at)
    }
    expect(reached).toEqual([...Array(Math.min(count, 4)).keys()])
  })
}
