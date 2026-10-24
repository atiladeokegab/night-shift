import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// Let them watch (#291) in a real Chrome: the tab is really shared (the flag accepts Chrome's prompt) and its
// frames really drawn, scaled and sent; offline, the server's note is none. A fake YouTube player stands in.

const KOBE = /^Basketball ?Kobe's 81/

// Chrome's new headless mode (channel chromium): the headless shell cannot share a tab
test.use({ channel: 'chromium', launchOptions: { args: ['--auto-accept-this-tab-capture', '--autoplay-policy=no-user-gesture-required'] } })

test('Let them watch shares the tab, sends a 512 px JPEG every 4 s, and Stop ends it at once', async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  const frames: { image: string; t: number; at: number; status?: number }[] = []
  await page.route('**/replays/*/look', async (r) => {
    const frame = { ...r.request().postDataJSON(), at: Date.now() }
    frames.push(frame)
    // the first frame goes to the server; offline, the replay calls all its lines within seconds and
    // then takes no more frames (410), so the later ones are answered here as a running replay would
    if (frames.length > 1) return r.fulfill({ json: { note: null } })
    const res = await r.fetch()
    frame.status = res.status()
    await r.fulfill({ response: res })
  })
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()

  await page.getByRole('button', { name: 'Let them watch' }).click()
  await expect(page.locator('.watching .chip')).toHaveText("They're watching")
  await expect(page.getByRole('status').filter({ hasText: "They're watching the screen" })).toBeAttached()
  await expect.poll(() => frames.length, { timeout: 15_000 }).toBeGreaterThanOrEqual(2)

  const [first, second] = frames
  const size = await page.evaluate(async (b64) => {
    const img = new Image()
    img.src = `data:image/jpeg;base64,${b64}`
    await img.decode()
    return [img.naturalWidth, img.naturalHeight]
  }, first.image)
  expect(size[0]).toBe(512)
  expect(size[1]).toBeGreaterThan(200) // the tab's own shape, scaled
  expect(typeof first.t).toBe('number')
  expect(second.at - first.at).toBeGreaterThan(3500)
  expect(first.status).toBe(200)

  await page.getByRole('button', { name: 'Stop: they stop watching' }).click()
  await expect(page.getByRole('button', { name: 'Let them watch' })).toBeVisible()
  const sent = frames.length
  await page.waitForTimeout(5000)
  expect(frames.length).toBe(sent)
})
