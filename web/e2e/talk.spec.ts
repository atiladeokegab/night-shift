import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// Talk to the commentator (#380) in a real browser: the token route and the ElevenLabs session are faked, so
// no key and no microphone. A fake YouTube player shows whether the match pauses and where it resumes.

const KOBE = /^Basketball ?Kobe's 81/

// Stands in for Vite's pre-bundled @elevenlabs/client: startSession connects at once and records its options.
const FAKE_CLIENT = `
export class Conversation {
  static async startSession(opts) {
    const talk = (window.talk = { opts, ended: 0 })
    setTimeout(() => opts.onConnect?.({ conversationId: 'fake' }), 50)
    return { endSession: async () => { talk.ended++; opts.onDisconnect?.() } }
  }
}
`

type Talk = { opts: { signedUrl: string; dynamicVariables: { ctx: string } }; ended: number }
type Player = { getCurrentTime(): number; getPlayerState(): number }
const PLAYING = 1
const PAUSED = 2

async function openKobe(page: Page, token: { status: number; json?: object }) {
  const asked: string[] = []
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.route(/\/node_modules\/\.vite\/deps\/@elevenlabs_client\.js/, (r) =>
    r.fulfill({ contentType: 'text/javascript', body: FAKE_CLIENT }))
  await page.route('**/converse/*/*/token?*', (r) => {
    asked.push(r.request().url())
    return r.fulfill({ status: token.status, json: token.json ?? { detail: 'not configured' } })
  })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.locator('.caption .cap-text')).toBeVisible({ timeout: 45_000 })
  await expect.poll(() => state(page)).toBe(PLAYING)
  return asked
}
const player = (page: Page) => page.evaluate(() => {
  const p = (window as unknown as { fakePlayer: Player }).fakePlayer
  return { t: p.getCurrentTime(), state: p.getPlayerState() }
})
const state = async (page: Page) => (await player(page)).state
const talk = (page: Page) => page.evaluate(() => (window as unknown as { talk?: Talk }).talk ?? null)

test('Talk pauses the match, and ending the talk resumes it from the same moment', async ({ page }) => {
  const asked = await openKobe(page, { status: 200, json: { signed_url: 'wss://fake.example/talk', ctx: 'the match so far' } })
  const button = page.getByRole('button', { name: 'Talk' })
  await expect(button).toBeEnabled()
  await button.click()

  const resume = page.getByRole('button', { name: 'Resume' })
  await expect(resume).toHaveAttribute('aria-pressed', 'true')
  expect(await state(page)).toBe(PAUSED)
  await expect(page.getByRole('status').filter({ hasText: /^Paused/ })).toBeAttached()
  expect(asked).toHaveLength(1)
  expect(new URL(asked[0]).searchParams.get('moment_idx')).toMatch(/^\d+$/)
  expect(await talk(page)).toMatchObject({ opts: { signedUrl: 'wss://fake.example/talk', dynamicVariables: { ctx: 'the match so far' } } })

  // the match holds while they talk
  const held = (await player(page)).t
  await page.waitForTimeout(1500)
  expect((await player(page)).t).toBe(held)

  await resume.click()
  await expect(page.getByRole('button', { name: 'Talk' })).toHaveAttribute('aria-pressed', 'false')
  expect((await talk(page))?.ended).toBe(1)
  await expect.poll(() => state(page)).toBe(PLAYING)
  const after = (await player(page)).t
  expect(after).toBeGreaterThanOrEqual(held)
  expect(after - held).toBeLessThan(1) // from where it stopped, not ahead by the talk's length
})

test('Talk is a keyboard control with a name: Enter starts it, Escape ends it and resumes', async ({ page }) => {
  await openKobe(page, { status: 200, json: { signed_url: 'wss://fake.example/talk', ctx: 'c' } })
  const button = page.getByRole('button', { name: 'Talk' })
  await expect(button).toBeEnabled()
  await expect(button).toHaveAttribute('title', /talk with the commentator/)

  // reachable by Tab alone, from the top of the page
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())
  let reached = false
  for (let i = 0; i < 80 && !reached; i++) {
    await page.keyboard.press('Tab')
    reached = await button.evaluate((b) => b === document.activeElement)
  }
  expect(reached).toBe(true)

  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Resume' })).toBeVisible()
  expect(await state(page)).toBe(PAUSED)
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Talk' })).toBeVisible()
  await expect.poll(() => state(page)).toBe(PLAYING)
})

test('a 503 from the token route says why and leaves Ask working, the match playing', async ({ page }) => {
  const asks: string[] = []
  page.on('request', (r) => r.method() === 'POST' && /\/ask$/.test(r.url()) && asks.push(r.postDataJSON().question))
  await openKobe(page, { status: 503 })
  await page.getByRole('button', { name: 'Talk' }).click()

  await expect(page.getByRole('status').filter({ hasText: 'Talking is not available just now. Ask still works.' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
  expect(await talk(page)).toBeNull() // no session was started
  await expect.poll(() => state(page)).toBe(PLAYING) // the pause the talk made is undone

  const ask = page.locator('#ask-q')
  await expect(ask).toBeEnabled()
  await ask.fill('Who leads?')
  await ask.press('Enter')
  await expect.poll(() => asks).toEqual(['Who leads?'])
})

test('Escape while it is still connecting cancels the talk: no session opens later and the match plays on', async ({ page }) => {
  let release = () => {}
  const gate = new Promise<void>((resolve) => (release = resolve))
  await openKobe(page, { status: 200 })
  await page.route('**/converse/*/*/token?*', async (r) => { // the latest route wins: this slow one
    await gate
    await r.fulfill({ json: { signed_url: 'wss://fake.example/talk', ctx: 'c' } })
  })
  await page.getByRole('button', { name: 'Talk' }).click()
  await expect(page.getByRole('button', { name: 'Connecting' })).toBeDisabled()
  expect(await state(page)).toBe(PAUSED)

  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Talk' })).toBeEnabled()
  await expect.poll(() => state(page)).toBe(PLAYING)
  release()
  await page.waitForTimeout(500)
  const late = await talk(page)
  expect(late === null || late.ended === 1).toBe(true) // never left open while the match plays
  expect(await state(page)).toBe(PLAYING) // and hanging it up did not stop the match again
  await expect(page.getByRole('button', { name: 'Talk' })).toHaveAttribute('aria-pressed', 'false')
})
