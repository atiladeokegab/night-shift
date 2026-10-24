import assert from 'node:assert/strict'
import { test } from 'node:test'
import { adapterRows, autonomyRows, nextAdapter } from './proof.ts'

test('under the target, the figure counts toward it', () => {
  assert.deepEqual(nextAdapter(12, 25), { value: '12 of 25', note: null })
})

test('at or over the target, it never reads "66 of 25" and says there are enough', () => {
  const { value, note } = nextAdapter(66, 25)
  assert.doesNotMatch(value, / of /)
  assert.equal(value, 'Ready to train')
  assert.equal(note, '66 fixes recorded · 25 needed: enough for the next adapter')
  assert.equal(nextAdapter(25, 25).note, '25 fixes recorded · 25 needed: enough for the next adapter')
})

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

const record = { status: 'ready' as const, version: null, score: null, target: null, passed: null, kept: null, recorded_at: '2026-10-24T16:00:00+00:00' }

test("one row per Mubit task, saying only what its latest record says", () => {
  const rows = adapterRows({
    line_check: { ...record, version: 1, score: 82, passed: true },
    where_are_we: { ...record, status: 'training', kept: 0 },
  })
  assert.deepEqual(rows, ['Commentary: not recorded', 'Where are we?: training, 0 kept', 'Line check: v1, 82%, Passed'])
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
  assert.deepEqual(adapterRows({ commentary: { ...record, status: 'not_trained' } })[0], 'Commentary: not trained')
})

test('before core reports adapters, no rows', () => {
  assert.deepEqual(adapterRows(undefined), [])
})
