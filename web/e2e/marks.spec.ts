import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// Every mapped moment's mark is on the timeline from the start, not added as the stream reaches it: the
// replay here sends only the cold open's welcome, so no line is said. A mark turns amber (done) once the
// picture reaches its moment, and closing the cover changes no mark.

const KOBE = /^Basketball ?Kobe's 81/
const MAP = JSON.parse(readFileSync(new URL('../../data/video/basketball-0020500591.json', import.meta.url), 'utf8')) as {
  moments: { idx: number; video_t: number }[]
}
const welcome = {
  sport: 'basketball', match_id: '0020500591', idx: 0, period: 1, clock: '12:00', type: 'Stat', team: 'Los Angeles Lakers',
  players: {}, outcome: 'cold open welcome', score: { home: 0, away: 0 }, detail: {},
}

test('every mark is on the timeline before the first line, and turns amber as the picture reaches it', async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'marks-replay' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream', body: `event: moment\ndata: ${JSON.stringify(welcome)}\n\n`,
  }))
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()

  const marks = page.locator('.scrub .mk')
  await expect(marks).toHaveCount(MAP.moments.length)
  await expect(page.locator('.scrub .mk.done')).toHaveCount(0)
  await expect(page.locator('.log li')).toHaveCount(0) // no line yet

  await page.getByRole('button', { name: 'Close your eyes' }).click()
  await expect(page.getByRole('button', { name: 'Close your eyes' })).toHaveAttribute('aria-pressed', 'true')
  await expect(marks).toHaveCount(MAP.moments.length)
  await expect(page.locator('.scrub .mk.done')).toHaveCount(0)

  const first = Math.min(...MAP.moments.map((m) => m.video_t)) + 0.5
  await page.waitForFunction(() => (window as unknown as { fakePlayer?: { getPlayerState(): number } }).fakePlayer?.getPlayerState() === 1)
  await page.evaluate((t) => (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer.seekTo(t), first)
  const reached = MAP.moments.filter((m) => m.video_t <= first).length
  await expect(page.locator('.scrub .mk.done')).toHaveCount(reached)
  await expect(marks).toHaveCount(MAP.moments.length)
})
