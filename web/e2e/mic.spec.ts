import { expect, test, type Page } from '@playwright/test'

// Mic on (#286) in a real browser, with a fake recognizer standing in for the browser's: the toggle and what it
// says, hold-to-talk standing down while it is on, and the viewer's voice hushing the line on air (barge-in).

const KOBE = /^Basketball ?Kobe's 81/

type Rec = { started: boolean; stopped: boolean; continuous: boolean }
type Fake = { recs: Rec[]; spoken: string[]; cancels: number; say(text: string, final: boolean): void }

// `available` false: the browser has no speech recognition at all.
async function fakeMic(page: Page, available: boolean) {
  await page.addInitScript((available) => {
    const w = window as unknown as Fake & Record<string, unknown>
    for (const name of ['SpeechRecognition', 'webkitSpeechRecognition']) delete w[name]
    w.spoken = []
    w.cancels = 0
    // The line on air stays on air (a headless browser has no voice), so a barge-in has something to hush.
    window.speechSynthesis.speak = (u: SpeechSynthesisUtterance) => void w.spoken.push(u.text)
    window.speechSynthesis.cancel = () => void w.cancels++
    if (!available) return
    type On = { onresult?: (e: unknown) => void; onend?: () => void }
    w.recs = []
    w.webkitSpeechRecognition = class {
      started = false
      stopped = false
      continuous = true
      constructor() {
        w.recs.push(this as unknown as Rec)
      }
      start() {
        this.started = true
      }
      stop() {
        this.stopped = true
      }
    }
    w.say = (text, final) =>
      (w.recs.at(-1) as unknown as On).onresult?.({ results: [Object.assign([{ transcript: text }], { isFinal: final })] })
  }, available)
}

async function openKobe(page: Page) {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await expect(page.locator('#ask-q')).toBeEnabled()
}
const blur = (page: Page) => page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())

test('Mic on: listens, hushes the line on air when the viewer talks, asks once, and hands back to hold-to-talk', async ({ page }) => {
  const asks: string[] = []
  page.on('request', (r) => r.method() === 'POST' && /\/ask$/.test(r.url()) && asks.push(r.postDataJSON().question))
  await fakeMic(page, true)
  await openKobe(page)

  const toggle = page.getByRole('button', { name: 'Mic on' })
  const hold = page.locator('button.mic')
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByText('Hands-free · use headphones')).toBeVisible()
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText('Listening · use headphones')).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as Fake).recs.map((r) => [r.started, r.continuous]))).toEqual([[true, false]])

  // Hold-to-talk stands down: its button is disabled and the space bar starts nothing.
  await expect(hold).toBeDisabled()
  await blur(page)
  await page.keyboard.down('Space')
  await page.keyboard.up('Space')
  expect(await page.evaluate(() => (window as unknown as Fake).recs.length)).toBe(1)

  // The line on air, heard back through the mic: nothing hushed, nothing asked.
  await expect.poll(() => page.evaluate(() => (window as unknown as Fake).spoken.length), { timeout: 30_000 }).toBeGreaterThan(0)
  const echo = await page.evaluate(() => {
    const w = window as unknown as Fake
    const before = w.cancels
    w.say(w.spoken.at(-1)!, true)
    return w.cancels - before
  })
  expect(echo).toBe(0)

  // The viewer talks: the line on air is hushed at once (barge-in reaches the speech's hush), then the
  // finished sentence is asked once and answered in the log.
  const barged = await page.evaluate(() => {
    const w = window as unknown as Fake
    const before = w.cancels
    w.say('who is guarding Kobe', false)
    return w.cancels - before
  })
  expect(barged).toBe(1)
  await page.evaluate(() => (window as unknown as Fake).say('who is guarding Kobe tonight', true))
  await expect(page.locator('.log li.qa').first()).toContainText('who is guarding Kobe tonight', { timeout: 30_000 })
  expect(asks).toEqual(['who is guarding Kobe tonight'])

  // Off: the recognizer stops, a late result is not asked, and hold-to-talk (the space bar) works again.
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  expect(await page.evaluate(() => (window as unknown as Fake).recs[0].stopped)).toBe(true)
  await page.evaluate(() => (window as unknown as Fake).say('and the score', true))
  await expect(hold).toBeEnabled()
  await blur(page)
  await page.keyboard.down('Space')
  expect(await page.evaluate(() => (window as unknown as Fake).recs.map((r) => [r.started, r.continuous]).at(-1))).toEqual([true, false])
  await page.keyboard.up('Space')
  expect(await page.evaluate(() => (window as unknown as Fake).recs.at(-1)!.stopped)).toBe(true)
  expect(await page.evaluate(() => (window as unknown as Fake).recs.length)).toBe(2)
  expect(asks).toEqual(['who is guarding Kobe tonight'])
})

test('with no speech recognition in the browser, neither Mic on nor the hold-to-talk mic shows', async ({ page }) => {
  await fakeMic(page, false)
  await openKobe(page)
  await expect(page.getByRole('button', { name: 'Mic on' })).toHaveCount(0)
  await expect(page.locator('button.mic')).toHaveCount(0)
  await expect(page.locator('#ask-q')).toBeEnabled() // typing still works
})
