import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// Layout glitches a judge-style screenshot pass found (#170). The replay is mocked: one moment and its line
// arrive on the stream, so no replay runs.

const sse = (events: [string, unknown][]) => events.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('')

async function replay(page: Page, events: [string, unknown][], video = false) {
  await page.route('**/matches', async (r) => {
    const response = await r.fetch()
    const matches = await response.json()
    for (const match of matches) {
      if (video && match.match_id === '0020500591') match.video_start = 490.5
      else delete match.youtube_id // These layout checks do not exercise a player clock.
    }
    await r.fulfill({ response, json: matches })
  })
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
  const chip = page.locator('#pane-lines .pill.check', { hasText: 'May be wrong' })
  await expect(chip).toBeVisible()
  await expect(chip.locator('.sr-only')).toHaveText('Checker model: event may be wrong')
  const box = await inside(page, '#pane-lines .pill.check', '#pane-lines .log li')
  expect(box.height, 'chip height').toBeLessThan(32)
})

test('the cricket Follow card keeps its table and Unfollow inside its padding at 390', async ({ page }) => {
  const moment = {
    sport: 'cricket', match_id: '1298150', idx: 0, period: 1, clock: '1.1', type: 'Wicket', team: 'India',
    players: { batter: 'Babar Azam', bowler: 'Arshdeep Singh' }, outcome: 'lbw', score: { home: 1, away: 1 }, detail: {},
  }
  const line = { line_id: 'c-1', match_id: '1298150', moment_idx: 0, text: 'Babar Azam goes for a duck.', latency_ms: 900 }
  const phase = (runs: number, balls: number) => ({ runs, balls, outs: 0 })
  const profile = {
    player: 'Babar Azam', team: 'Pakistan', sport: 'cricket', window: { from: '2021-01-01', to: '2022-10-22' },
    before: { games: 18, batting: { powerplay: phase(312, 247), middle: phase(250, 190), death: phase(49, 25) }, bowling: { balls: 0, runs: 0, wickets: 0, economy: null } },
    tonight: { batting: { powerplay: phase(0, 1), middle: phase(0, 0), death: phase(0, 0) }, bowling: { balls: 0, runs: 0, wickets: 0 } },
    n: 462, small_sample: false, text: '',
  }
  await replay(page, [['moment', moment], ['line', line]])
  await page.route('**/replays/*/players?*', (r) => r.fulfill({ json: [{ name: 'Babar Azam', team: 'Pakistan', record: true, named: true }] }))
  await page.route('**/replays/*/players/*/profile?*', (r) => r.fulfill({ json: profile }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: /^Cricket/ }).first().click()
  await page.getByRole('tab', { name: 'Follow' }).click()
  await page.getByRole('combobox', { name: 'Follow a player' }).fill('Babar')
  await page.getByRole('button', { name: /Babar Azam/ }).click()
  await expect(page.getByText('Batting by phase')).toBeVisible()
  await expect(page.locator('.profile .zones td').first()).toHaveText('312 off 247 · 0 off 1 tonight')
  await inside(page, '.profile .zones', '.profile', 20)
  await inside(page, '.profile .panel-h .btn', '.profile', 20)
})

test('Talk reads "Connecting" at full strength while its session starts', async ({ page }) => {
  const moment = {
    sport: 'basketball', match_id: '0020500591', idx: 3, video_t: 490.5, period: 3, clock: '09:36', type: 'Field goal',
    team: 'Los Angeles Lakers', players: { shooter: 'Kobe Bryant' }, outcome: '2 points', score: { home: 53, away: 69 },
    detail: { play: "Bryant 10' Running Jump Shot (30 PTS)", player_points: 30 },
  }
  await replay(page, [['moment', moment]], true)
  await page.route('**/converse/*/*/token*', () => new Promise(() => {})) // the token never comes: Connecting stays
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: /^Basketball ?Kobe's 81/ }).click()
  await page.getByRole('button', { name: 'Talk' }).click()
  const connecting = page.getByRole('button', { name: 'Connecting' })
  await expect(connecting).toBeDisabled()
  await expect(connecting).toHaveAttribute('aria-busy', 'true')
  await expect(connecting).toHaveCSS('opacity', '1')
})
