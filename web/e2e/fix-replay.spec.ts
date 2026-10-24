import { appendFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { FAKE_YT } from './fakeYT'

// The stage path "fix a flagged line in the review queue, then a replay that gets it right": a stored line
// that says a wrong score is fixed by hand in the Review queue, a new replay of the same match is started,
// and at that moment it says the corrected line, never the old one. Offline: the fix goes through the fake provider.

const KOBE = /^Basketball ?Kobe's 81/
const KOBE_ID = '0020500591' // idx 4: Bryant's three for 41 points, Lakers 65, Raptors 75
const SAID = 'Kobe Bryant from deep, three points! Lakers trail'
// a tag of letters per run: the dev store outlives a run, and a wording already fixed is not queued again
const TAG = Math.random().toString(36).replace(/[^a-z]/g, '').slice(0, 6)
const WRONG = `${SAID} fifty-eight to seventy-five, Bryant with forty-one. ${TAG}`
const RIGHT = `${SAID} sixty-five to seventy-five, Bryant with forty-one. ${TAG}`

const ID = `e2e-wrong-score-${Date.now()}`

test('a line fixed in the review queue is what a new replay says at that moment', async ({ page }) => {
  // the flagged line, as an earlier replay would have stored it (the server reads the store file afresh)
  const dir = join(tmpdir(), 'touchline-e2e')
  mkdirSync(dir, { recursive: true })
  appendFileSync(join(dir, 'lines.jsonl'), JSON.stringify({
    line_id: ID, match_id: KOBE_ID, moment_idx: 4, sport: 'basketball', speaker: 'lead', text: WRONG,
    created_at: new Date().toISOString(),
  }) + '\n')

  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')

  // 1. the review queue shows the flagged line; 2. it is fixed with the corrected text
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Review' }).click()
  const card = page.locator('li.flag').filter({ hasText: WRONG }).getByRole('button', { name: /^Fix this line/ }).first()
  await expect(page.getByText(WRONG).first()).toBeVisible({ timeout: 30_000 })
  await card.click()
  await page.getByLabel('Corrected line').fill(RIGHT)
  const sent = page.waitForResponse((r) => r.url().endsWith(`/lines/${ID}/fix`) && r.request().method() === 'POST')
  await page.getByRole('button', { name: /^Send/ }).click()
  expect((await sent).status()).toBe(200)
  await expect(page.getByText(/^Fix sent/)).toBeVisible()
  await expect(page.getByText(WRONG)).toHaveCount(0) // its card left the queue

  // 3. a new replay of the same match; 4. at that moment it says the corrected line, not the old one
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Matches' }).click()
  await page.getByRole('button', { name: KOBE }).click()
  const log = page.locator('ul.log > li:not(.qa)')
  await expect(log.filter({ hasText: RIGHT }).first()).toBeVisible({ timeout: 60_000 })
  await expect(log.filter({ hasText: WRONG })).toHaveCount(0)
})
