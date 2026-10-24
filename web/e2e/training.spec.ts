import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

// #400: a producer's fix on the review page, then the chain on the same screen: the fix saved, the two
// Score check examples it sent with their Mubit request ids, the example count before → after and the
// adapter it waits for. Every route is mocked: no keys, nothing sent.

const item = {
  line_id: 'l1', match_id: '3754092', match: 'Chelsea v Tottenham Hotspur', sport: 'football', moment_idx: 28,
  clock: '57:41', period: 2, score: 'Chelsea 1, Tottenham 2', play: 'A substitution', text: 'Tottenham still lead one-nil.',
  wrong: ['one-nil is not the score (1-2)'], lines: 1, others: [], later_check: false,
}
const FIXED = 'Tottenham still lead two-one.'
const AT = '2026-10-24T21:40:00+00:00'
const fix = { line_id: 'l1', corrected_text: FIXED, reason: 'Wrong number', created_at: AT, mubit_request_id: 'req_fix', recorded: true }
const examples = [
  { line_id: 'l1', text: item.text, gold: 'wrong', kind: 'corrected', mubit_request_id: 'req_said', created_at: AT, source: 'fix' },
  { line_id: 'l1', text: FIXED, gold: 'ok', kind: 'matched', mubit_request_id: 'req_fixed', created_at: AT, source: 'fix' },
]
const scorecheck = (n: number) => ({
  examples_sent: n, by_source: { answer_key: n - 2, auto_fixed: 0, human: 2 }, from_fixes_by_kind: {},
  held_out: {}, next_training: 'after 01:00 UK', recorded: null,
})

test('a fix on the review page shows its Score check examples sent to training', async ({ page }) => {
  let fixed = false
  await page.route('**/review', (r) => r.fulfill({ json: fixed ? [] : [item] }))
  await page.route('**/ledger', (r) => r.fulfill({ json: { sent: 0, rows: [] } }))
  await page.route('**/stats', (r) => r.fulfill({ json: { scorecheck: scorecheck(fixed ? 814 : 812) } }))
  await page.route('**/lines/l1/fix', (r) => ((fixed = true), r.fulfill({ json: fix })))
  await page.route('**/lines/l1', (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: fixed ? examples : [] } }))

  await page.goto('/#review')
  await page.locator('.flag .btn.primary').click()
  await page.locator('#fix-text').fill(FIXED)
  await page.getByRole('button', { name: 'Send fix' }).click()

  const panel = page.getByRole('region', { name: 'Sent to training' })
  await expect(panel).toContainText('Fix saved: request req_fix')
  await expect(panel).toContainText('Line as said: wrong · request req_said')
  await expect(panel).toContainText('Fixed text: ok · request req_fixed')
  await expect(panel).toContainText('Score check examples: 812 → 814')
  await expect(panel).toContainText('Training run pending')
  await expect(panel).not.toContainText(/model updated|learns live/i)

  const { violations } = await new AxeBuilder({ page }).include('.training').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  expect(violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => v.id)).toEqual([])
})

// Live has fixes whose line as said was already sent: one example only. Its count shows at once, not
// after the minute the page waits for a second.
test('a fix that sends one Score check example shows the count as it lands', async ({ page }) => {
  let fixed = false
  await page.route('**/review', (r) => r.fulfill({ json: fixed ? [] : [item] }))
  await page.route('**/ledger', (r) => r.fulfill({ json: { sent: 0, rows: [] } }))
  await page.route('**/stats', (r) => r.fulfill({ json: { scorecheck: scorecheck(fixed ? 2161 : 2160) } }))
  await page.route('**/lines/l1/fix', (r) => ((fixed = true), r.fulfill({ json: fix })))
  await page.route('**/lines/l1', (r) => r.fulfill({ json: { ...item, fix, scorecheck_examples: fixed ? examples.slice(1) : [] } }))

  await page.goto('/#review')
  await page.locator('.flag .btn.primary').click()
  await page.locator('#fix-text').fill(FIXED)
  await page.getByRole('button', { name: 'Send fix' }).click()

  const panel = page.getByRole('region', { name: 'Sent to training' })
  await expect(panel).toContainText('Fixed text: ok · request req_fixed')
  await expect(panel).toContainText('Score check examples: 2,160 → 2,161', { timeout: 10_000 })
  await expect(panel).not.toContainText(/NaN|undefined|Line as said/)
})
