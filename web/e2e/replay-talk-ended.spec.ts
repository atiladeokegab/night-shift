import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

const KOBE = /^Basketball ?Kobe's 81/
const FIRST = {
  sport: 'basketball', match_id: '0020500591', idx: 0, period: 1, clock: '10:35', type: 'Field goal',
  team: 'Toronto Raptors', players: { shooter: 'Morris Peterson', assist: 'Mike James' }, outcome: '2 points',
  score: { home: 2, away: 2 },
  detail: { play: "Peterson 17' Jump Shot (2 PTS) (James 1 AST)", player_points: 2, tied: true },
}

type Options = {
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: () => void
  onModeChange?: (event: { mode: string }) => void
  onMessage?: (event: { source: string }) => void
}
type Session = { endSession: () => Promise<void> }
type Probe = { options: Options[]; resolve: ((session: Session) => void)[]; ended: number }

async function fixtures(page: Page) {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.addInitScript(() => {
    ;(window as unknown as { __talkLifecycle: Probe }).__talkLifecycle = { options: [], resolve: [], ended: 0 }
  })
  await page.route(/elevenlabs_client\.js/, (r) => r.fulfill({
    contentType: 'application/javascript',
    body: `
      const probe = window.__talkLifecycle;
      export const Conversation = { startSession(options) {
        probe.options.push(options);
        return new Promise(resolve => probe.resolve.push(resolve));
      } };
    `,
  }))
}

async function open(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
}

async function resolveSession(page: Page, index: number) {
  await page.evaluate((i) => {
    const p = (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle
    p.options[i].onConnect?.()
    p.resolve[i]({ endSession: async () => { p.ended++ } })
  }, index)
}

test('a replay-gone Ask ends Talk before a delayed same-match restart can reuse it', async ({ page }) => {
  await fixtures(page)
  let replays = 0
  let releaseRestart!: () => void
  let restartRequested!: () => void
  const restartGate = new Promise<void>((resolve) => { releaseRestart = resolve })
  const restartSeen = new Promise<void>((resolve) => { restartRequested = resolve })
  await page.route('**/replays', async (r) => {
    if (++replays === 2) {
      restartRequested()
      await restartGate
    }
    await r.fulfill({ json: { replay_id: `talk-ended-${replays}` } })
  })
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    contentType: 'text/event-stream',
    body: `event: moment\ndata: ${JSON.stringify(FIRST)}\n\n`,
  }))
  await page.route('**/converse/*/*/token*', (r) => r.fulfill({
    json: { signed_url: 'wss://example.invalid/session', ctx: 'test-context' },
  }))
  await page.route('**/replays/*/ask', (r) => r.fulfill({ status: 404, json: { detail: "no replay 'gone'" } }))

  await open(page)
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options.length)).toBe(1)
  await resolveSession(page, 0)
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()

  await page.locator('#ask-q').fill("What's the score?")
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const alert = page.getByRole('alert').filter({ hasText: 'This replay has ended' })
  await expect(alert).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.ended)).toBe(1)

  await page.getByRole('button', { name: 'Start again' }).click()
  await restartSeen
  await expect(page.getByRole('button', { name: 'Resume' })).toHaveCount(0)
  await page.evaluate(() => {
    const p = (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle
    p.options[0].onConnect?.()
    p.options[0].onError?.()
    p.options[0].onModeChange?.({ mode: 'listening' })
    p.options[0].onMessage?.({ source: 'user' })
    p.options[0].onDisconnect?.()
  })
  await expect(page.getByRole('button', { name: 'Resume' })).toHaveCount(0)
  await expect(page.getByRole('status').filter({ hasText: 'conversation dropped' })).toHaveCount(0)

  releaseRestart()
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
})

test('a transient stream reconnect does not turn into an ended replay', async ({ page }) => {
  await fixtures(page)
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: 'reconnect-control' } }))
  let streams = 0
  await page.route('**/replays/*/stream', async (r) => {
    if (++streams === 1) return r.abort()
    await r.fulfill({
      contentType: 'text/event-stream',
      body: `event: moment\ndata: ${JSON.stringify(FIRST)}\n\nevent: end\ndata: {}\n\n`,
    })
  })
  await open(page)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
  await expect(page.getByRole('alert').filter({ hasText: 'This replay has ended' })).toHaveCount(0)
  expect(streams).toBeGreaterThanOrEqual(2)
})
