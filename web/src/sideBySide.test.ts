import assert from 'node:assert/strict'
import { test } from 'node:test'
import { viewOf, type Line, type Pair, type Report } from './sideBySide.ts'
import data from '../../data/side_by_side.json' with { type: 'json' }

const line = (cost_usd: number | null): Line => ({ text: 'Goal!', model: 'm', first_word_ms: 500, latency_ms: 800, cost_usd })
const pair = (big: number, adapter: Line | null): Pair => ({
  sport: 'football', match_id: '1', match: 'A v B, 2022', moment_idx: 0, clock: '09:11', moment: 'Shot',
  big: line(big), adapter, verdict: adapter ? 'agree' : 'not compared: no adapter line',
})
const report = (pairs: Pair[]): Report => ({
  recorded_on: '2026-10-24', big_model: 'm', pairs,
  adapter: data.adapter, // the recorded file the panel reads, so the fixture can't go stale
})

test('no adapter line: the big model is the baseline, ours is not yet measured', () => {
  const view = viewOf(report([pair(0.0016, null), pair(0.0018, null)]))
  assert.equal(view.paired, false)
  assert.ok(Math.abs(view.bigCost! - 0.0017) < 1e-12)
  assert.equal(view.oursCost, null)
  assert.equal(view.ours, "no version has passed Mubit's test yet") // never "training"
})

test('a recorded adapter line: both lines side by side, ours costed from its own lines only', () => {
  const view = viewOf(report([pair(0.002, line(0.0002)), pair(0.002, null)]))
  assert.equal(view.paired, true)
  assert.equal(view.bigCost, 0.002)
  assert.equal(view.oursCost, 0.0002)
  assert.equal(view.ours, 'not ready') // the recorded status, as eval/side_by_side.py wrote it
})

test('an adapter line with no cost stays unmeasured, never $0', () => {
  assert.equal(viewOf(report([pair(0.002, line(null))])).oursCost, null)
})
