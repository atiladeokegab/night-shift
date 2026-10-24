import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// Let them watch (#291) in a real Chrome: our code's frames really drawn, scaled and sent; offline, the
// server's note is none. Chrome's share prompt is not ours to test, so getDisplayMedia gives a moving 1280x720
// canvas's stream, as a shared tab would. A fake YouTube player stands in.

const KOBE = /^Basketball ?Kobe's 81/

test.use({ launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] } })

test('Let them watch shares the tab, sends a 512 px JPEG every 4 s, and Stop ends it at once', async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  const frames: { image: string; t: number; at: number; status?: number }[] = []
  await page.route('**/replays/*/look', async (r) => {
    const frame = { ...r.request().postDataJSON(), at: Date.now() }
    frames.push(frame)
    // the first frame goes to the server too, which checks its body before anything else. Offline, the
    // replay calls all its lines within seconds and may take no more frames (410), so the page is
    // answered here as a running replay would
    if (frames.length === 1) frame.status = (await r.fetch()).status()
    await r.fulfill({ json: { note: null } })
  })
  await page.addInitScript(() => {
    navigator.mediaDevices.getDisplayMedia = async (options) => {
      Object.assign(window, { shareAsked: options })
      const canvas = Object.assign(document.createElement('canvas'), { width: 1280, height: 720 })
      const g = canvas.getContext('2d')!
      let n = 0
      setInterval(() => {
        g.fillStyle = `hsl(${(n += 7) % 360} 60% 40%)`
        g.fillRect(0, 0, 1280, 720)
      }, 100)
      return canvas.captureStream(10)
    }
  })
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()

  await page.getByRole('button', { name: 'Let them watch' }).click()
  await expect(page.locator('.watching .chip')).toHaveText("They're watching")
  await expect(page.getByRole('status').filter({ hasText: "They're watching the screen" })).toBeAttached()
  await expect.poll(() => frames.length, { timeout: 15_000 }).toBeGreaterThanOrEqual(2)
  expect(await page.evaluate(() => (window as unknown as { shareAsked: object }).shareAsked)).toMatchObject({ preferCurrentTab: true })

  const [first, second] = frames
  const size = await page.evaluate(async (b64) => {
    const img = new Image()
    img.src = `data:image/jpeg;base64,${b64}`
    await img.decode()
    return [img.naturalWidth, img.naturalHeight]
  }, first.image)
  expect(size[0]).toBe(512)
  expect(size[1]).toBe(288) // the shared picture's own shape, scaled
  expect(typeof first.t).toBe('number')
  expect(second.at - first.at).toBeGreaterThan(3500)
  expect([200, 410]).toContain(first.status) // a valid frame: never 413 or 422

  await page.getByRole('button', { name: 'Stop: they stop watching' }).click()
  await expect(page.getByRole('button', { name: 'Let them watch' })).toBeVisible()
  const sent = frames.length
  await page.waitForTimeout(5000)
  expect(frames.length).toBe(sent)
})
