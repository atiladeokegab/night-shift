import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

const KOBE = /^Basketball ?Kobe's 81/
const FIRST = {
  sport: 'basketball', match_id: '0020500591', idx: 0, period: 1, clock: '10:35', type: 'Field goal',
  team: 'Toronto Raptors', players: { shooter: 'Morris Peterson', assist: 'Mike James' }, outcome: '2 points',
  score: { home: 2, away: 2 }, video_t: 478,
  detail: { play: "Peterson 17' Jump Shot (2 PTS) (James 1 AST)", player_points: 2, tied: true },
}

type Session = { endSession: () => Promise<void> }
type Options = {
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: () => void
  onModeChange?: (event: { mode: string }) => void
  onMessage?: (event: { source: string }) => void
}
type Probe = { options: Options[]; resolve: ((session: Session) => void)[]; ended: number }

async function fixtures(page: Page) {
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  let replay = 0
  await page.route('**/replays', (r) => r.fulfill({ json: { replay_id: `talk-${++replay}` } }))
  await page.route('**/replays/*/stream', (r) => r.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: `event: moment\ndata: ${JSON.stringify(FIRST)}\n\nevent: end\ndata: {}\n\n`,
  }))
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

async function live(page: Page) {
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

test('a token that resolves after leaving the match never opens a session', async ({ page }) => {
  await fixtures(page)
  let release!: () => void
  let requested!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  const seen = new Promise<void>((resolve) => { requested = resolve })
  await page.route('**/converse/*/*/token*', async (r) => {
    requested()
    await gate
    await r.fulfill({ json: { signed_url: 'wss://example.invalid/session', ctx: 'test-context' } })
  })
  await live(page)
  await page.getByRole('button', { name: 'Talk' }).click()
  await seen
  await page.getByRole('button', { name: 'About', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'The describer that checks itself.' })).toBeVisible()
  release()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options.length)).toBe(0)
})

test('a token from the old replay cannot start Talk after an in-place sport switch', async ({ page }) => {
  await fixtures(page)
  let release!: () => void
  let requested!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  const seen = new Promise<void>((resolve) => { requested = resolve })
  let tokens = 0
  await page.route('**/converse/*/*/token*', async (r) => {
    if (++tokens === 1) {
      requested()
      await gate
    }
    await r.fulfill({ json: { signed_url: 'wss://example.invalid/session', ctx: 'test-context' } })
  })
  await live(page)
  await page.getByRole('button', { name: 'Talk' }).click()
  await seen
  await page.getByRole('button', { name: 'Cricket', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Cricket', exact: true })).toHaveAttribute('aria-pressed', 'true')
  release()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options.length)).toBe(0)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
})

test('a late SDK session is ended and its callbacks cannot end a newer replay session', async ({ page }) => {
  await fixtures(page)
  await page.route('**/converse/*/*/token*', (r) => r.fulfill({
    json: { signed_url: 'wss://example.invalid/session', ctx: 'test-context' },
  }))
  await live(page)
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options.length)).toBe(1)

  await page.getByRole('button', { name: 'Cricket', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Cricket', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.evaluate(() => {
    const p = (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle
    p.options[0].onConnect?.()
  })
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options.length)).toBe(2)
  await resolveSession(page, 1)
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()

  await resolveSession(page, 0)
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.ended)).toBe(1)
  await page.evaluate(() => {
    const options = (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options
    options[0].onError?.()
    options[0].onModeChange?.({ mode: 'listening' })
    options[0].onMessage?.({ source: 'user' })
    options[0].onDisconnect?.()
  })
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'conversation dropped' })).toHaveCount(0)

  await page.clock.install()
  await page.evaluate(() => {
    const options = (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options
    options[0].onModeChange?.({ mode: 'listening' })
  })
  await page.clock.fastForward(12_001)
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
  await page.evaluate(() => {
    const p = (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle
    p.options[1].onModeChange?.({ mode: 'listening' })
    p.options[0].onMessage?.({ source: 'user' })
  })
  await page.clock.fastForward(12_001)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.ended)).toBe(2)
})

test('normal Talk connects and resumes when ended', async ({ page }) => {
  await fixtures(page)
  await page.route('**/converse/*/*/token*', (r) => r.fulfill({
    json: { signed_url: 'wss://example.invalid/session', ctx: 'test-context' },
  }))
  await live(page)
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.options.length)).toBe(1)
  await resolveSession(page, 0)
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
  await page.getByRole('button', { name: 'Resume' }).click()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __talkLifecycle: Probe }).__talkLifecycle.ended)).toBe(1)
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
})
