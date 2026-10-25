import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

const FAKE_CLIENT = `
export class Conversation {
  static async startSession(opts) {
    const talk = (window.talk = { opts, ended: 0 })
    setTimeout(() => opts.onConnect?.({ conversationId: 'fake' }), 10)
    return { endSession: async () => { talk.ended++; opts.onDisconnect?.() } }
  }
}
`

const videoMatch = {
  match_id: 'cold-open-ask-video', sport: 'cricket', title: 'India v Pakistan', sample: true,
  home: 'India', away: 'Pakistan', youtube_id: 'fake-video', video_start: 0, embed: true,
}
const cold = {
  sport: 'cricket', match_id: videoMatch.match_id, idx: 0, period: 1, clock: '0.0', type: 'Stat', team: 'India',
  players: {}, outcome: 'cold open welcome', score: { runs: 0, wickets: 0 }, detail: {},
}
// Replay-generated introductions are synthetic Stat moments. Even when timed, they must not unlock
// questions about the real feed events which are still ahead of the video.
const timedIntro = { ...cold, clock: '0.2', outcome: 'The match is underway', video_t: 2 }
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

async function wireVideo(page: import('@playwright/test').Page, wicketAt: number) {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route(/elevenlabs_client\.js/, (r) => r.fulfill({ contentType: 'application/javascript', body: FAKE_CLIENT }))
  await page.route('**/matches', (r) => r.fulfill({ json: [videoMatch] }))
  await page.route('**/voices', (r) => r.fulfill({ json: [] }))
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'cold-open-ask-video-replay' } }))
  const mappedWicket = { ...wicket, video_t: wicketAt }
  const mappedWicketLine = { ...wicketLine, video_t: wicketAt }
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: [
      ['moment', cold],
      ['line', intro],
      ['moment', timedIntro],
      ['moment', mappedWicket],
      ['line', mappedWicketLine],
    ].map(([type, value]) => `event: ${type}\ndata: ${JSON.stringify(value)}\n\n`).join(''),
  }))
  const requests = { askPosts: 0, tokenPosts: 0 }
  await page.route('**/replays/*/ask', async (r) => {
    requests.askPosts += 1
    const { question, moment_idx } = r.request().postDataJSON()
    await r.fulfill({ json: { line_id: 'cold-open-answer', moment_idx, question, text: 'The first ball takes a wicket.', off_air: true } })
  })
  await page.route('**/converse/*/*/token?*', async (r) => {
    requests.tokenPosts += 1
    await r.fulfill({ json: { signed_url: 'wss://fake.example/talk', ctx: 'cold-open-test' } })
  })
  return requests
}

test('video cold open disables Ask until the same-index mapped event is visible', async ({ page }) => {
  const requests = await wireVideo(page, 30)
  await page.goto('/')
  await page.getByRole('button', { name: /India v Pakistan/ }).click()
  await expect(page.locator('#ask-q')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Where are we?' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Ask', exact: true })).toBeDisabled()
  await page.waitForFunction(() => Boolean((window as unknown as { fakePlayer?: { getPlayerState(): number } }).fakePlayer?.getPlayerState() === 1))
  await page.evaluate(() => {
    const player = (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer
    player.seekTo(2)
  })
  await expect(page.locator('.bug .clock')).toContainText('0.2')
  await expect(page.locator('#ask-q')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Where are we?' })).toBeDisabled()
  expect(requests.askPosts).toBe(0)
  expect(requests.tokenPosts).toBe(0)
  await page.waitForTimeout(15_500) // Let the quiet-spell Ask fire while the first mapped moment is still ahead.
  expect(requests.askPosts).toBe(0)
  expect(requests.tokenPosts).toBe(0)
  await expect(page.getByRole('button', { name: 'Talk' })).toHaveCount(0)

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
  await expect.poll(() => requests.askPosts).toBe(1)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeVisible()
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
  await expect.poll(() => requests.tokenPosts).toBe(1)
  await page.evaluate(() => {
    const player = (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer
    player.seekTo(0)
  })
  await expect(page.getByRole('button', { name: 'Talk' })).toHaveCount(0)
  await expect.poll(() => page.evaluate(() => (window as unknown as { talk?: { ended: number } }).talk?.ended)).toBe(1)
})

test('a timed synthetic Stat does not unlock Ask before the wicket at 9 seconds', async ({ page }) => {
  const requests = await wireVideo(page, 9)
  await page.goto('/')
  await page.getByRole('button', { name: /India v Pakistan/ }).click()
  await page.waitForFunction(() => Boolean((window as unknown as { fakePlayer?: { getPlayerState(): number } }).fakePlayer?.getPlayerState() === 1))
  await page.evaluate(() => (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer.seekTo(2))
  await expect(page.locator('.bug .clock')).toContainText('0.2')
  await expect(page.locator('#ask-q')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Where are we?' })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Talk' })).toHaveCount(0)
  expect(requests.askPosts).toBe(0)
  expect(requests.tokenPosts).toBe(0)

  await page.evaluate(() => (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer.seekTo(9))
  await expect(page.locator('.caption .cap-text')).toContainText('Bowled him first ball!')
  await expect(page.locator('#ask-q')).toBeEnabled()
  await page.locator('#ask-q').fill('What happened on the first ball?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => requests.askPosts).toBe(1)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeVisible()
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect.poll(() => requests.tokenPosts).toBe(1)
})

test('a match without video can be asked about from its first real moment', async ({ page }) => {
  await page.route(/elevenlabs_client\.js/, (r) => r.fulfill({ contentType: 'application/javascript', body: FAKE_CLIENT }))
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
  let tokenPosts = 0
  await page.route('**/converse/*/*/token?*', async (r) => {
    tokenPosts += 1
    await r.fulfill({ json: { signed_url: 'wss://fake.example/talk', ctx: 'no-video-test' } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /Rovers v Harbour/ }).click()
  await expect(page.locator('#ask-q')).toBeEnabled()
  await page.locator('#ask-q').fill('Who scored?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect.poll(() => askPosts).toBe(1)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeVisible()
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
  await expect.poll(() => tokenPosts).toBe(1)
})
