import { expect, test, type Page } from '@playwright/test'

// A judge's first minute on the deployed site (make live-e2e): Chelsea v Spurs plays, lines keep coming past
// 40 s, the lead and the analyst both speak, every voice request answers 200, and the Proof card opens. It
// starts one real replay, so it costs about one replay's model and voice spend. A headless browser has no
// speech voice of its own, so a line the browser would speak ends after 2 s instead of never.

const BRIDGE = /Battle of the Bridge/ // Chelsea v Tottenham, 3754092

const lines = (page: Page) => page.locator('ul.log > li:not(.qa)')
const said = (page: Page, who: 'lead' | 'analyst') => page.locator(`ul.log .chip.${who}`).count()

test('Chelsea v Spurs keeps talking past 40 s, in both voices, and the Proof card opens', async ({ page }) => {
  const audio: { status: number; url: string }[] = []
  page.on('response', (r) => {
    if (/\/lines\/[^/]+\/audio/.test(r.url())) audio.push({ status: r.status(), url: r.url() })
  })
  await page.addInitScript(() => {
    window.speechSynthesis.speak = (u: SpeechSynthesisUtterance) => {
      setTimeout(() => u.onend?.(new SpeechSynthesisEvent('end', { utterance: u })), 2000)
    }
  })
  await page.goto('/')
  await page.getByRole('button', { name: BRIDGE }).first().click()
  const started = Date.now()

  await expect.poll(() => lines(page).count(), { timeout: 30_000 }).toBeGreaterThan(0)
  await page.waitForTimeout(40_000 - (Date.now() - started))
  const at40 = await lines(page).count()
  const clock = await page.locator('.clock').first().textContent()
  // the stall a judge saw: two lines, then nothing, the clock held at 04:00
  await expect
    .poll(() => lines(page).count(), { timeout: 45_000, message: `lines stuck at ${at40} after 40 s (clock ${clock})` })
    .toBeGreaterThan(at40)

  await expect.poll(() => said(page, 'lead'), { timeout: 30_000 }).toBeGreaterThan(0)
  await expect.poll(() => said(page, 'analyst'), { timeout: 30_000, message: 'the analyst never spoke' }).toBeGreaterThan(0)

  expect(audio.length, 'no line asked for its audio').toBeGreaterThan(0)
  expect(audio.filter((a) => a.status !== 200), 'voice requests that did not answer 200').toEqual([])

  const tab = page.getByRole('tab', { name: 'Proof' }) // the sidebar's tabs show only on narrow screens
  if (await tab.isVisible()) await tab.click()
  const proof = page.getByRole('region', { name: 'Proof' })
  await proof.scrollIntoViewIfNeeded()
  await expect(proof).toBeVisible()
  await expect(proof.getByRole('heading', { name: 'Proof' })).toBeVisible()
})
