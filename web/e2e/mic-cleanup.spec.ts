import { expect, test, type Page } from '@playwright/test'

const KOBE = /^Basketball ?Kobe's 81/
const ARGENTINA = /Argentina v France/

type ResultEvent = { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }
type Recognition = {
  stopped: boolean
  onresult: ((event: ResultEvent) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}
type MicHarness = {
  recs: Recognition[]
  result: (index: number, text: string, final: boolean) => void
  error: (index: number) => void
  end: (index: number) => void
}

async function fakeMic(page: Page) {
  await page.addInitScript(() => {
    type Harness = MicHarness & Record<string, unknown>
    const w = window as unknown as Harness
    for (const name of ['SpeechRecognition', 'webkitSpeechRecognition']) delete w[name]
    w.recs = []
    class FakeRecognition {
      stopped = false
      onresult: Recognition['onresult'] = null
      onerror: Recognition['onerror'] = null
      onend: Recognition['onend'] = null
      start() {}
      stop() { this.stopped = true }
      constructor() { w.recs.push(this as Recognition) }
    }
    w.webkitSpeechRecognition = FakeRecognition
    w.result = (index, text, final) => {
      const item = Object.assign([{ transcript: text }], { isFinal: final })
      w.recs[index].onresult?.({ results: [item] })
    }
    w.error = (index) => w.recs[index].onerror?.({ error: 'no-speech' })
    w.end = (index) => w.recs[index].onend?.()
  })
}

// These tests cover recognizer lifecycle, not video playback; use an explicit no-video match.
async function noVideoMatch(page: Page) {
  await page.route('**/matches', async (route) => {
    const response = await route.fetch()
    const matches = await response.json()
    await route.fulfill({
      response,
      json: matches.map(({ youtube_id, video_start, peak_video_start, ...match }: Record<string, unknown>) => match),
    })
  })
}

async function openKobe(page: Page) {
  await page.setViewportSize({ width: 1280, height: 900 })
  await noVideoMatch(page)
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await expect(page.locator('#ask-q')).toBeEnabled()
}

async function holdMic(page: Page) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  await page.keyboard.down('Space')
  await expect.poll(() => page.evaluate(() => (window as unknown as MicHarness).recs.length)).toBe(1)
}

async function nextMatch(page: Page) {
  await page.getByRole('button', { name: /Back to all matches/ }).click()
  await page.getByRole('button', { name: ARGENTINA }).click()
  await expect(page.locator('.vcard')).toHaveAttribute('aria-label', /Argentina v France/)
  await expect(page.locator('#ask-q')).toBeEnabled()
}

function watchAsks(page: Page) {
  const asks: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/ask$/.test(request.url())) asks.push(request.postDataJSON().question)
  })
  return asks
}

test('an old recognizer ending after a new match opens cannot ask its old transcript', async ({ page }) => {
  await fakeMic(page)
  const asks = watchAsks(page)
  await openKobe(page)
  await holdMic(page)

  await nextMatch(page)
  expect(await page.evaluate(() => (window as unknown as MicHarness).recs[0].stopped)).toBe(true)
  await page.evaluate(() => (window as unknown as MicHarness).result(0, 'old match question', false))
  await page.evaluate(() => (window as unknown as MicHarness).end(0))
  await page.waitForTimeout(500)

  expect(asks).not.toContain('old match question')
  await expect(page.locator('#ask-q')).toHaveValue('')
})

test('normal hold and release still sends the recognized question once', async ({ page }) => {
  await fakeMic(page)
  const asks = watchAsks(page)
  await openKobe(page)
  await holdMic(page)
  await page.evaluate(() => (window as unknown as MicHarness).result(0, 'who is guarding Kobe', false))
  await page.keyboard.up('Space')
  await page.evaluate(() => (window as unknown as MicHarness).end(0))

  await expect(page.locator('.log li.qa').first()).toContainText('who is guarding Kobe', { timeout: 30_000 })
  expect(asks).toEqual(['who is guarding Kobe'])
})
