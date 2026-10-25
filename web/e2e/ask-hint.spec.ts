import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// #514's gate, for a fan who cannot see it: while Ask waits for play it says so, once, and a player that
// fails (venue Wi-Fi, blocked autoplay, an embed error) opens Ask instead of leaving it closed for good.

const match = {
  match_id: 'ask-hint-video', sport: 'cricket', title: 'India v Pakistan', sample: true,
  home: 'India', away: 'Pakistan', youtube_id: 'fake-video', video_start: 0, embed: true,
}
const cold = {
  sport: 'cricket', match_id: match.match_id, idx: 0, period: 1, clock: '0.0', type: 'Stat', team: 'India',
  players: {}, outcome: 'cold open welcome', score: { runs: 0, wickets: 0 }, detail: {},
}
const wicket = {
  sport: 'cricket', match_id: match.match_id, idx: 0, period: 1, clock: '1.1', type: 'Wicket', team: 'India',
  players: { out: 'Batter', bowler: 'Bowler' }, outcome: 'Bowled', video_t: 30, score: { runs: 1, wickets: 1 }, detail: {},
}
const intro = { line_id: 'ask-hint-intro', match_id: match.match_id, moment_idx: 0, speaker: 'analyst', text: 'Welcome.', latency_ms: 1 }
const wicketLine = {
  line_id: 'ask-hint-wicket', match_id: match.match_id, moment_idx: 0, video_t: 30, speaker: 'lead', text: 'Bowled him first ball!', latency_ms: 1,
}
const HINT = 'Ask opens when play starts'
// The fake player errors where it would have been ready, as an embed refused on the venue's network does.
const ERRORING_YT = FAKE_YT.replace('opts.events?.onReady?.({ target: this })', 'opts.events?.onError?.({ data: 150, target: this })')

async function open(page: Page, yt: string) {
  let asks = 0
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: yt }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route('**/matches', (r) => r.fulfill({ json: [match] }))
  await page.route('**/voices', (r) => r.fulfill({ json: [] }))
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'ask-hint-replay' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: [['moment', cold], ['line', intro], ['moment', wicket], ['line', wicketLine]]
      .map(([type, value]) => `event: ${type}\ndata: ${JSON.stringify(value)}\n\n`).join(''),
  }))
  await page.route('**/replays/*/ask', async (r) => {
    asks += 1
    const { question, moment_idx } = r.request().postDataJSON()
    await r.fulfill({ json: { line_id: `ask-hint-answer-${asks}`, moment_idx, question, text: 'The first ball took a wicket.', off_air: true } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: /India v Pakistan/ }).click()
  return () => asks
}

test('while the cold open plays, Ask is closed and says once, politely, when it opens', async ({ page }) => {
  await open(page, FAKE_YT)
  const hint = page.locator('span.sr-only[aria-live="polite"]')
  await expect(page.locator('.caption .cap-text')).toContainText('Welcome.')
  await expect(page.locator('#ask-q')).toBeDisabled()
  await expect(page.locator('#ask-q')).toHaveAttribute('placeholder', HINT)
  await expect(hint).toHaveText(HINT)

  await page.waitForFunction(() => (window as unknown as { fakePlayer?: { getPlayerState(): number } }).fakePlayer?.getPlayerState() === 1)
  await page.evaluate(() => (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer.seekTo(30))
  await expect(page.locator('#ask-q')).toBeEnabled()
  await expect(hint).toHaveText('')
})

test('a player that errors opens Ask on the replay clock: the fan is never left without it', async ({ page }) => {
  const asks = await open(page, ERRORING_YT)
  await expect(page.locator('#ask-q')).toBeEnabled()
  await expect(page.locator('span.sr-only[aria-live="polite"]')).toHaveText('')
  await page.locator('#ask-q').fill('What happened on the first ball?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(asks).toBe(1)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeVisible()
})
