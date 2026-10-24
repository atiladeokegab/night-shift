import assert from 'node:assert/strict'
import { test } from 'node:test'
import { viewOf, type Line, type Pair, type Report } from './sideBySide.ts'

const line = (cost_usd: number | null): Line => ({ text: 'Goal!', model: 'm', first_word_ms: 500, latency_ms: 800, cost_usd })
const pair = (big: number, adapter: Line | null): Pair => ({
  sport: 'football', match_id: '1', match: 'A v B, 2022', moment_idx: 0, clock: '09:11', moment: 'Shot',
  big: line(big), adapter, verdict: adapter ? 'agree' : 'not compared: no adapter line',
})
const report = (pairs: Pair[]): Report => ({
  recorded_on: '2026-10-24', big_model: 'm', pairs,
  adapter: { name: null, status: 'not ready', adapters: 6, best_match_pct: 55.8, callable: false, why: '' },
})

test('no adapter line: the big model is the baseline, ours is not yet measured', () => {
  const view = viewOf(report([pair(0.0016, null), pair(0.0018, null)]))
  assert.equal(view.paired, false)
  assert.ok(Math.abs(view.bigCost! - 0.0017) < 1e-12)
  assert.equal(view.oursCost, null)
})

test('a recorded adapter line: both lines side by side, ours costed from its own lines only', () => {
  const view = viewOf(report([pair(0.002, line(0.0002)), pair(0.002, null)]))
  assert.equal(view.paired, true)
  assert.equal(view.bigCost, 0.002)
  assert.equal(view.oursCost, 0.0002)
})

test('an adapter line with no cost stays unmeasured, never $0', () => {
  assert.equal(viewOf(report([pair(0.002, line(null))])).oursCost, null)
})
