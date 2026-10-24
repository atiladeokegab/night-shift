import assert from 'node:assert/strict'
import { test } from 'node:test'
import { adapterGood, adapterRows, autonomyRows, TRAINING_LABEL } from './proof.ts'

const all = { called: 10, first_time: 6, auto_fixed: 2, to_human: 2 }
const kobe = { called: 6, first_time: 3, auto_fixed: 1, to_human: 2 }

test("the card's autonomy rows are this match's counts, then every match's, as /stats gives them", () => {
  const stats = { autonomy: all, autonomy_by_match: { '0020500591': kobe } }
  assert.deepEqual(autonomyRows(stats, '0020500591'), [['This match', kobe], ['All matches', all]])
  for (const [, a] of autonomyRows(stats, '0020500591')) assert.equal(a.first_time + a.auto_fixed + a.to_human, a.called)
})

test('a match with no calls yet counts zeros; no match, only all matches; no counts, no rows', () => {
  const none = { called: 0, first_time: 0, auto_fixed: 0, to_human: 0 }
  assert.deepEqual(autonomyRows({ autonomy: all, autonomy_by_match: {} }, '9636'), [['This match', none], ['All matches', all]])
  assert.deepEqual(autonomyRows({ autonomy: all }, null), [['All matches', all]])
  assert.deepEqual(autonomyRows({}, '9636'), [])
})

const record = { state: 'testing' as const, version: null, score: null, target: null, passed: null, kept: null, recorded_at: '2026-10-24T16:00:00+00:00' }

test("one row per Mubit task, saying only what its latest record says", () => {
  const rows = adapterRows({
    line_check: { ...record, version: 1, score: 82, passed: true },
    where_are_we: { ...record, state: 'collecting', kept: 0 },
  })
  assert.deepEqual(rows, ['Commentary: not recorded', 'Where are we?: collecting, 0 kept', 'Line check: v1, 82%, Passed'])
})

test("a failed gate in the console's words; a ready version with no verdict never reads as passed", () => {
  assert.deepEqual(
    adapterRows({ where_are_we: { ...record, version: 1, score: 55.8, target: 95, passed: false } })[1],
    'Where are we?: v1, 55.8%, below 95% target',
  )
  // a failed verdict the score doesn't explain stays "Failed": no score, a score at the target, a 0 target
  const failed = { ...record, version: 1, passed: false, target: 95 }
  assert.equal(adapterRows({ line_check: { ...failed, score: null } })[2], 'Line check: v1, Failed')
  assert.equal(adapterRows({ line_check: { ...failed, score: 95 } })[2], 'Line check: v1, 95%, Failed')
  assert.equal(adapterRows({ line_check: { ...failed, score: 0, target: 0 } })[2], 'Line check: v1, 0%, Failed')
  assert.deepEqual(adapterRows({ commentary: { ...record, version: 2, passed: false } })[0], 'Commentary: v2, Failed')
  assert.deepEqual(adapterRows({ commentary: { ...record, version: 3, score: 64.5 } })[0], 'Commentary: v3, 64.5%, verdict not recorded')
  assert.deepEqual(adapterRows({ commentary: { ...record, state: 'collecting' } })[0], 'Commentary: collecting')
})

test('before core reports adapters, no rows', () => {
  assert.deepEqual(adapterRows(undefined), [])
})

test('the Adapter row is green only for a recorded pass of the gate', () => {
  const adapter = { state: 'testing' as const, summary: '', kept: 31, agree: 23, total: 25, cost_measurable: false }
  assert.equal(adapterGood({ adapter: { ...adapter, state: 'passed' } }), true)
  // a version with no verdict or a failed gate, still collecting, or no adapter from core: never green
  assert.equal(adapterGood({ adapter }), false)
  assert.equal(adapterGood({ adapter: { ...adapter, state: 'collecting' } }), false)
  assert.equal(adapterGood({}), false)
})

test('the fix counts are headed as training data, never a bare "Training" that reads as under way', () => {
  assert.equal(TRAINING_LABEL, 'Training data')
})
