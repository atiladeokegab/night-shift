import { expect, test, type Page } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

const DEEP = '3869685' // Argentina v France; the delayed start lookup supplies its video offset.
const KOBE = /^Basketball ?Kobe's 81/

async function fakeVideo(page: Page) {
  await page.route('https://www.youtube.com/iframe_api', (route) =>
    route.fulfill({ contentType: 'text/javascript', body: FAKE_YT }),
  )
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (route) => route.abort())
}

function replayStarts(page: Page) {
  const ids: string[] = []
  page.on('request', (request) => {
    if (request.method() !== 'POST' || new URL(request.url()).pathname !== '/replays') return
    ids.push(request.postDataJSON().match_id)
  })
  return ids
}

async function holdStartLookup(page: Page) {
  let release!: () => void
  let requested!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  const seen = new Promise<void>((resolve) => { requested = resolve })
  await page.route(`**/matches/${DEEP}/start**`, async (route) => {
    requested()
    await gate
    await route.fulfill({ json: { video_start: 321 } })
  })
  return { seen, release }
}

async function staleReplayStarted(page: Page, release: () => void) {
  const stale = page.waitForRequest(
    (request) => request.method() === 'POST' && new URL(request.url()).pathname === '/replays' &&
      request.postDataJSON().match_id === DEEP,
    { timeout: 1500 },
  ).then(() => true, (error: Error) => {
    if (error.name !== 'TimeoutError') throw error
    return false
  })
  release()
  return stale
}

test('a deep-link lookup cannot replace a match chosen while it is pending', async ({ page }) => {
  await fakeVideo(page)
  const starts = replayStarts(page)
  const lookup = await holdStartLookup(page)
  await page.goto(`/?match=${DEEP}&at=5`)
  await lookup.seen

  await page.getByRole('button', { name: KOBE }).click()
  await expect(page.locator('.vcard')).toHaveAttribute('aria-label', /Toronto/)
  expect(starts).toContain('0020500591')

  expect(await staleReplayStarted(page, lookup.release)).toBe(false)
  await expect(page.locator('.vcard')).toHaveAttribute('aria-label', /Toronto/)
})

test('a deep-link lookup cannot reopen a match after navigation away', async ({ page }) => {
  await fakeVideo(page)
  const lookup = await holdStartLookup(page)
  await page.goto(`/?match=${DEEP}&at=5`)
  await lookup.seen

  await page.getByRole('button', { name: 'About', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'The describer that checks itself.' })).toBeVisible()

  expect(await staleReplayStarted(page, lookup.release)).toBe(false)
  await expect(page.getByRole('heading', { name: 'The describer that checks itself.' })).toBeVisible()
})

test('an untouched deep link opens its match at the requested moment', async ({ page }) => {
  await fakeVideo(page)
  const starts = replayStarts(page)
  await page.route(`**/matches/${DEEP}/start**`, (route) =>
    route.fulfill({ json: { video_start: 321 } }),
  )
  const startRequest = page.waitForRequest(
    (r) => r.method() === 'POST' && new URL(r.url()).pathname === '/replays',
  )
  await page.goto(`/?match=${DEEP}&at=5`)

  await expect(page.locator('.vcard')).toHaveAttribute('aria-label', /Argentina v France/)
  await expect.poll(() => starts.at(-1)).toBe(DEEP)
  await expect.poll(async () => page.evaluate(() =>
    (window as unknown as { fakePlayer?: { t: number } }).fakePlayer?.t,
  )).toBe(321)
  const request = await startRequest
  expect(request.postDataJSON()).toMatchObject({ match_id: DEEP, start_idx: 5 })
})
