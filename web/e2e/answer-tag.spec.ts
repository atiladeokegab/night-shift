import { expect, test } from '@playwright/test'
import { FAKE_YT, toFirstEvent } from './fakeYT'

const match = {
  match_id: 'answer-tag-fixture', sport: 'cricket', title: 'India v Pakistan', sample: true,
  home: 'India', away: 'Pakistan', youtube_id: 'fake-video', video_start: 0, embed: true,
}
const cold = {
  sport: 'cricket', match_id: match.match_id, idx: 0, period: 1, clock: '0.0', type: 'Stat', team: 'India',
  players: {}, outcome: 'cold open welcome', score: { runs: 0, wickets: 0 }, detail: {},
}
const wicket = {
  sport: 'cricket', match_id: match.match_id, idx: 0, period: 1, clock: '1.1', type: 'Wicket', team: 'India',
  players: { out: 'Batter', bowler: 'Bowler' }, outcome: 'Bowled', video_t: 9,
  score: { runs: 1, wickets: 1 }, detail: {},
}
const intro = { line_id: 'intro', match_id: match.match_id, moment_idx: 0, speaker: 'analyst', text: 'Welcome.', latency_ms: 1 }
const wicketLine = {
  line_id: 'wicket-line', match_id: match.match_id, moment_idx: 0, video_t: 9, speaker: 'lead',
  text: 'Bowled him first ball!', latency_ms: 1,
}
const second = {
  ...wicket, idx: 1, clock: '1.2', players: { out: 'Next', bowler: 'Bowler' }, video_t: 20, score: { runs: 1, wickets: 2 },
}
const secondLine = { ...wicketLine, line_id: 'second-line', moment_idx: 1, video_t: 20, text: 'Another one, two in two!' }

test('an answer at duplicate first idx tags the real wicket, not the cold open', async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route('**/matches', (r) => r.fulfill({ json: [match] }))
  await page.route('**/voices', (r) => r.fulfill({ json: [] }))
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'answer-tag-replay' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: [
      ['moment', cold], ['line', intro], ['moment', wicket], ['line', wicketLine],
    ].map(([type, value]) => `event: ${type}\ndata: ${JSON.stringify(value)}\n\n`).join(''),
  }))
  await page.route('**/replays/*/ask', async (r) => {
    const { question, moment_idx } = r.request().postDataJSON()
    await r.fulfill({ json: { line_id: `answer-${question}`, moment_idx, question, text: 'The wicket has put Pakistan one down.', off_air: true } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /India v Pakistan/ }).click()
  await expect(page.locator('.caption .cap-text')).toContainText('Welcome.')

  // The wicket is already in the received stream, but it is still queued behind the picture:
  // at the cold open there is no event to ask about yet (#514).
  await expect(page.locator('#ask-q')).toBeDisabled()

  await page.waitForFunction(() => Boolean((window as unknown as { fakePlayer?: unknown }).fakePlayer))
  await page.evaluate(() => {
    const player = (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer
    player.seekTo(9)
  })
  await expect(page.locator('.caption .cap-text')).toContainText('Bowled him first ball!')
  await expect(page.locator('.caption .tag')).toHaveText('Over 1.1 · Wicket')

  await page.locator('#ask-q').fill('What happened to the batter?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.locator('.caption .cap-state')).toBeVisible()
  await expect(page.locator('.caption .tag')).toHaveText('at Over 1.1')
})

test('a delayed answer keeps the moment visible when its Ask began', async ({ page }) => {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route('**/matches', (r) => r.fulfill({ json: [match] }))
  await page.route('**/voices', (r) => r.fulfill({ json: [] }))
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'delayed-answer-tag-replay' } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: [
      ['moment', cold], ['line', intro], ['moment', wicket], ['line', wicketLine], ['moment', second], ['line', secondLine],
    ].map(([type, value]) => `event: ${type}\ndata: ${JSON.stringify(value)}\n\n`).join(''),
  }))

  let signalRequest = () => {}
  let releaseResponse = () => {}
  const requested = new Promise<void>((resolve) => { signalRequest = resolve })
  const held = new Promise<void>((resolve) => { releaseResponse = resolve })
  await page.route('**/replays/*/ask', async (r) => {
    const { question, moment_idx } = r.request().postDataJSON()
    signalRequest()
    await held
    await r.fulfill({ json: { line_id: 'delayed-answer', moment_idx, question, text: 'The wicket has put Pakistan one down.', off_air: true } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: /India v Pakistan/ }).click()
  await expect(page.locator('.caption .cap-text')).toContainText('Welcome.')
  await toFirstEvent(page, 9)
  await expect(page.locator('.caption .cap-text')).toContainText('Bowled him first ball!')
  await page.locator('#ask-q').fill('What happened to the batter?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await requested

  // The response is still held while the player releases the next wicket.
  await page.evaluate(() => (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer.seekTo(20))
  await expect(page.locator('.log')).toContainText('Another one, two in two!')
  releaseResponse()

  await expect(page.locator('.caption .cap-state')).toBeVisible()
  await expect(page.locator('.caption .tag')).toHaveText('at Over 1.1')
  await expect(page.locator('.log li.qa .at')).toContainText('at Over 1.1')
})
