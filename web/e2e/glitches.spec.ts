import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// Layout glitches a judge-style screenshot pass found (#170). The replay is mocked: one moment and its line
// arrive on the stream, so no replay runs.

const sse = (events: [string, unknown][]) => events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')

async function replay(page: Page, events: [string, unknown][]) {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'glitch-1' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: sse(events) }))
}

const inside = async (page: Page, inner: string, outer: string, pad = 0) => {
  const a = (await page.locator(inner).first().boundingBox())!
  const b = (await page.locator(outer).first().boundingBox())!
  expect(a.x, `${inner} left`).toBeGreaterThanOrEqual(b.x + pad - 0.5)
  expect(a.x + a.width, `${inner} right`).toBeLessThanOrEqual(b.x + b.width - pad + 0.5)
  expect(a.y + a.height, `${inner} bottom`).toBeLessThanOrEqual(b.y + b.height + 0.5)
  return a
}

test('a flagged line check stays a small chip inside Lines at 1440', async ({ page }) => {
  const moment = {
    sport: 'basketball', match_id: '0020500591', idx: 0, period: 1, clock: '10:35', type: 'Field goal',
    team: 'Toronto Raptors', players: { shooter: 'Morris Peterson' }, outcome: '2 points', score: { home: 2, away: 2 }, detail: {},
  }
  const line = { line_id: 'l-1', match_id: '0020500591', moment_idx: 0, text: 'Peterson opens the scoring.', latency_ms: 900 }
  const check = { line_id: 'l-1', labels: { score: 'ok', leader: 'ok', player_total: 'ok', event: 'wrong' }, wrong: ['event'] }
  await replay(page, [['moment', moment], ['line', line], ['linecheck', check]])
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: /^Basketball ?Kobe's 81/ }).click()
  const chip = page.locator('#pane-lines .pill.check', { hasText: 'Checker model: event may be wrong' })
  await expect(chip).toBeVisible()
  const box = await inside(page, '#pane-lines .pill.check', '#pane-lines .log li')
  expect(box.height, 'chip height').toBeLessThan(32)
})
