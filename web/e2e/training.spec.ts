import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type Route } from '@playwright/test'

// #400: a producer's fix on the review page, then the chain on the same screen: the fix saved, the Score
// check examples it sent with their Mubit request ids, the example count before → after and the adapter it
// waits for. Every route is mocked: no keys, nothing sent.

const item = {
  line_id: 'l1', match_id: '3754092', match: 'Chelsea v Tottenham Hotspur', sport: 'football', moment_idx: 28,
  clock: '57:41', period: 2, score: 'Chelsea 1, Tottenham 2', play: 'A substitution', text: 'Tottenham still lead one-nil.',
  wrong: ['one-nil is not the score (1-2)'], lines: 1, others: [], later_check: false,
}
const FIXED = 'Tottenham still lead two-one.'
const AT = '2026-10-24T21:40:00+00:00'
const UID = 'fix-new'
const fix = { line_id: 'l1', fix_uid: UID, corrected_text: FIXED, reason: 'Wrong number', created_at: AT, mubit_request_id: 'req_fix', recorded: true }
const examples = [
  { line_id: 'l1', fix_uid: UID, text: item.text, gold: 'wrong', kind: 'corrected', mubit_request_id: 'req_said', created_at: AT, source: 'fix' },
  { line_id: 'l1', fix_uid: UID, text: FIXED, gold: 'ok', kind: 'matched', mubit_request_id: 'req_fixed', created_at: AT, source: 'fix' },
]
const receipt = (sent: number, failed = false) => ({ fix_uid: UID, line_id: 'l1', sent, failed, created_at: AT })
const scorecheck = (n: number) => ({
  examples_sent: n, by_source: { answer_key: n - 2, auto_fixed: 0, human: 2 }, from_fixes_by_kind: {},
  held_out: {}, next_training: 'after 01:00 UK', recorded: null,
})

// The review queue with one card; `line` answers GET /lines/l1, `stats` /stats (812 before the fix, 814 after).
async function mock(page: Page, line: (r: Route) => unknown, stats?: (r: Route, fixed: boolean) => unknown) {
  const state = { fixed: false, posts: 0, reads: 0 }
  await page.route('**/review', (r) => r.fulfill({ json: state.fixed ? [] : [item] }))
  await page.route('**/ledger', (r) => r.fulfill({ json: { sent: 0, rows: [] } }))
  await page.route('**/stats', (r) => (stats ? stats(r, state.fixed) : r.fulfill({ json: { scorecheck: scorecheck(state.fixed ? 814 : 812) } })))
  await page.route('**/lines/l1/fix', (r) => ((state.fixed = true), state.posts++, r.fulfill({ json: fix })))
  await page.route('**/lines/l1', (r) => (state.reads++, line(r)))
  return state
}

async function sendFix(page: Page) {
  await page.goto('/#review')
  await page.locator('.flag .btn.primary').click()
  await page.locator('#fix-text').fill(FIXED)
  await page.getByRole('radio', { name: 'Tone' }).check() // no Line check example: its reads would mix in
  await page.getByRole('button', { name: 'Send fix' }).click()
}

test('a fix on the review page shows its Score check examples sent to training', async ({ page }) => {
  await mock(page, (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: examples, scorecheck_receipts: [receipt(2)] } }))
  await sendFix(page)

  const panel = page.locator('.training')
  await expect(panel.getByRole('heading')).toHaveText('Sent to training')
  await expect(panel).toContainText('Fix saved: request req_fix')
  await expect(panel).toContainText('Line as said: wrong · request req_said')
  await expect(panel).toContainText('Fixed text: ok · request req_fixed')
  await expect(panel).toContainText('Score check examples: 814 → 814')
  await expect(panel).toContainText('Training run pending')
  await expect(panel).not.toContainText(/model updated|learns live/i)

  const { violations } = await new AxeBuilder({ page }).include('.training').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)).toEqual([])
})

// The count before is read once the fix is saved, and after once its examples are in: it goes up.
test('the count goes up from the read after the save to the read after the receipt', async ({ page }) => {
  let reads = 0
  await mock(page, (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: examples, scorecheck_receipts: [receipt(2)] } }),
    (r, fixed) => r.fulfill({ json: { scorecheck: scorecheck(!fixed ? 2160 : reads++ ? 2163 : 2161) } }))
  await sendFix(page)
  await expect(page.locator('.training')).toContainText('Score check examples: 2,161 → 2,163')
})

// Live has fixes whose line as said was already sent (#427): one example, and its receipt says so.
test('a fix that sends one Score check example shows it as soon as its receipt is in', async ({ page }) => {
  await mock(page, (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: examples.slice(1), scorecheck_receipts: [receipt(1)] } }))
  await sendFix(page)

  const panel = page.locator('.training')
  await expect(panel.getByRole('heading')).toHaveText('Sent to training')
  await expect(panel).toContainText('Fixed text: ok · request req_fixed')
  await expect(panel).not.toContainText(/NaN|undefined|Line as said/)
})

// A held-out match's fix (live, #411's check on Brighton v Bristol City) sends nothing, and the panel says why.
test('a fix on a held-out match says it is held out, never "already sent"', async ({ page }) => {
  await mock(page, (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: [], scorecheck_receipts: [{ ...receipt(0), held_out: true }] } }))
  await sendFix(page)

  const panel = page.locator('.training')
  await expect(panel.getByRole('heading')).toHaveText('Not sent to training: this match is held out')
  await expect(panel).toContainText('This match is held out of training, so the eval that scores the model stays fair')
  await expect(panel).not.toContainText('already sent')
})

// Review blocker 1: the save never waits on /stats. Held open, the fix is still posted and saved.
test('a stalled /stats never holds the fix: it is posted and the panel opens', async ({ page }) => {
  const state = await mock(page, (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: [], scorecheck_receipts: [] } }),
    () => {}) // never answered
  await sendFix(page)

  await expect(page.locator('.training')).toContainText('Fix saved: request req_fix')
  expect(state.posts).toBe(1)
})

// Review blocker 2: an earlier fix of the same line, in the same second, is never this fix's receipt.
test("another fix's examples on the same line are never shown as this fix's", async ({ page }) => {
  const earlier = examples.map((x, i) => ({ ...x, fix_uid: 'fix-old', mubit_request_id: `req_old_${i}` }))
  await mock(page, (r) => r.fulfill({ json: {
    ...item, fix, scorecheck_examples: earlier,
    scorecheck_receipts: [{ ...receipt(2), fix_uid: 'fix-old' }, receipt(0)],
  } }))
  await sendFix(page)

  const panel = page.locator('.training')
  await expect(panel.getByRole('heading')).toHaveText('Not sent to training')
  await expect(panel).toContainText('No new Score check example')
  await expect(panel).not.toContainText('req_old')
})

// Review blockers 3 and 4: with GET /lines/{id} stalled the heading stays neutral, and the reads give up
// at the deadline as "not confirmed", never "none sent".
test('a stalled read stays neutral and ends unconfirmed at the deadline', async ({ page }) => {
  await page.clock.install()
  const state = await mock(page, () => {}) // GET /lines/l1 never answers
  await sendFix(page)

  const panel = page.locator('.training')
  await page.clock.runFor(3_000)
  await expect(panel.getByRole('heading')).toHaveText('Score check: waiting for the receipt')
  await page.clock.runFor(70_000)
  await expect(panel.getByRole('heading')).toHaveText('Training send not confirmed')
  await expect(panel).not.toContainText('No new Score check example')
  expect(state.reads).toBeGreaterThan(1) // each stalled read gave up and the next one went
})

// Review blocker 3: closing the panel stops its reads.
test('Close stops the panel reading', async ({ page }) => {
  await page.clock.install()
  const state = await mock(page, (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: [], scorecheck_receipts: [] } }))
  await sendFix(page)

  const panel = page.locator('.training')
  await page.clock.runFor(4_000)
  await expect.poll(() => state.reads).toBeGreaterThan(0)
  await panel.getByRole('button', { name: 'Close' }).click()
  await expect(panel).toHaveCount(0)
  const closed = state.reads
  await page.clock.runFor(30_000)
  expect(state.reads).toBe(closed)
})
