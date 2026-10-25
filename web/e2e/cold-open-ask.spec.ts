import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

const videoMatch = {
  match_id: 'cold-open-ask-video', sport: 'cricket', title: 'India v Pakistan', sample: true,
  home: 'India', away: 'Pakistan', youtube_id: 'fake-video', video_start: 0, embed: true,
}
const cold = {
  sport: 'cricket', match_id: videoMatch.match_id, idx: 0, period: 1, clock: '0.0', type: 'Stat', team: 'India',
  players: {}, outcome: 'cold open welcome', score: { runs: 0, wickets: 0 }, detail: {},
}
const wicket = {
  sport: 'cricket', match_id: videoMatch.match_id, idx: 0, period: 1, clock: '1.1', type: 'Wicket', team: 'India',
  players: { out: 'Batter', bowler: 'Bowler' }, outcome: 'Bowled', video_t: 30,
  score: { runs: 1, wickets: 1 }, detail: {},
}
const intro = { line_id: 'cold-open-intro', match_id: videoMatch.match_id, moment_idx: 0, speaker: 'analyst', text: 'Welcome.', latency_ms: 1 }
const wicketLine = {
  line_id: 'cold-open-wicket-line', match_id: videoMatch.match_id, moment_idx: 0, video_t: 30, speaker: 'lead',
  text: 'Bowled him first ball!', latency_ms: 1,
}
const noVideoMatch = {
  match_id: 'cold-open-ask-no-video', sport: 'football', title: 'Rovers v Harbour', sample: true,
  home: 'Rovers', away: 'Harbour',
}
const firstGoal = {
  sport: 'football', match_id: noVideoMatch.match_id, idx: 0, period: 1, clock: '4:12', type: 'Shot', team: 'Rovers',
  players: { scorer: 'Forward' }, outcome: 'Goal', score: { home: 1, away: 0 }, detail: { shot_type: 'Goal' },
}

test('video cold open disables Ask until the same-index mapped event is visible', async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route('**/matches', (r) => r.fulfill({ json: [videoMatch] }))
  await page.route('**/voices', (r) => r.fulfill({ json: [] }))
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'cold-open-ask-video-replay' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: [
      ['moment', cold],
      ['line', intro],
      ['moment', wicket],
      ['line', wicketLine],
    ].map(([type, value]) => `event: ${type}\ndata: ${JSON.stringify(value)}\n\n`).join(''),
  }))
  let askPosts = 0
  await page.route('**/replays/*/ask', async (r) => {
    askPosts += 1
    const { question, moment_idx } = r.request().postDataJSON()
    await r.fulfill({ json: { line_id: 'cold-open-answer', moment_idx, question, text: 'The first ball takes a wicket.', off_air: true } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /India v Pakistan/ }).click()
  await expect(page.locator('#ask-q')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Where are we?' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Ask', exact: true })).toBeDisabled()
  await page.waitForFunction(() => Boolean((window as unknown as { fakePlayer?: { getPlayerState(): number } }).fakePlayer?.getPlayerState() === 1))
  await page.waitForTimeout(15_500) // Let the quiet-spell Ask fire while the first mapped moment is still ahead.
  expect(askPosts).toBe(0)

  await page.waitForFunction(() => Boolean((window as unknown as { fakePlayer?: unknown }).fakePlayer))
  await page.evaluate(() => {
    const player = (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer
    player.seekTo(30)
  })
  await expect(page.locator('.caption .cap-text')).toContainText('Bowled him first ball!')
  await expect(page.locator('.caption .tag')).toHaveText('Over 1.1 · Wicket')
  await expect(page.locator('#ask-q')).toBeEnabled()
  await page.locator('#ask-q').fill('What happened on the first ball?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => askPosts).toBe(1)
})

test('a match without video can be asked about from its first real moment', async ({ page }) => {
  await page.route('**/matches', (r) => r.fulfill({ json: [noVideoMatch] }))
  await page.route('**/voices', (r) => r.fulfill({ json: [] }))
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'cold-open-ask-no-video-replay' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: `event: moment\ndata: ${JSON.stringify(firstGoal)}\n\n`,
  }))
  let askPosts = 0
  await page.route('**/replays/*/ask', async (r) => {
    askPosts += 1
    const { question, moment_idx } = r.request().postDataJSON()
    await r.fulfill({ json: { line_id: 'no-video-answer', moment_idx, question, text: 'Rovers lead one nil.', off_air: true } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /Rovers v Harbour/ }).click()
  await expect(page.locator('#ask-q')).toBeEnabled()
  await page.locator('#ask-q').fill('Who scored?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => askPosts).toBe(1)
})
