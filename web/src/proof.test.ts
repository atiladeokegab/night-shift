import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { adapterGood, adapterRows, autonomyRows, checkText, exampleText, FALLBACK_NOTE, FLAG_NOTE, heldoutRow, linecheckRow, TRAINING_LABEL, voiceRow } from './proof.ts'
import type { HeldOut } from './types.ts'

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

test("a checked line's chip says all ok or the fields the checker model flags, and nothing without a reply (#298)", () => {
  const labels = { score: 'ok', leader: 'not_said', player_total: 'wrong', event: 'ok' } as const
  assert.equal(checkText({ line_id: 'a', labels, wrong: [] }), 'Checker model: all ok')
  assert.equal(checkText({ line_id: 'a', labels, wrong: ['player_total'] }), 'Checker model: player total may be wrong')
  assert.equal(checkText({ line_id: 'a', labels: null, wrong: [] }), null)
  assert.equal(checkText(undefined), null)
  assert.equal(linecheckRow({ checked: 9, flags: 2, rules_missed: 2, fixes_sent: 1 }), '9 checked · 2 flagged (2 the rules missed) · 1 fixes sent to it')
})

test("the voice row says when browser speech reads the lines, and why; nothing while ElevenLabs does", () => {
  const quota = { provider: 'browser' as const, last_error: 'quota_exceeded', since: '2026-10-24T18:02:11+00:00' }
  assert.equal(voiceRow(quota, false), 'Voice: browser fallback (ElevenLabs unavailable) · quota exceeded since 18:02 UTC')
  assert.equal(voiceRow({ provider: 'elevenlabs', last_error: null, since: null }, false), null)
  assert.equal(voiceRow(undefined, false), null)
  // the page fell back before /stats caught up: the note, without a reason it doesn't know
  assert.equal(voiceRow({ provider: 'elevenlabs', last_error: null, since: null }, true), FALLBACK_NOTE)
})

test("today's fix examples on the Proof row, and a fixed line's example in words that claim no model update", () => {
  const s = { checked: 9, flags: 2, rules_missed: 2, fixes_sent: 4, examples_today: 3, examples_today_by_kind: { corrected: 2, leader_only: 1 } }
  assert.equal(linecheckRow(s), '9 checked · 2 flagged (2 the rules missed) · 4 fixes sent to it · 3 examples from fixes today (2 corrected, 1 leader only)')
  assert.equal(linecheckRow({ ...s, examples_today: 0, examples_today_by_kind: {} }).endsWith('· 0 examples from fixes today'), true)
  const ex = { line_id: 'w', kind: 'corrected' as const, mubit_request_id: 'req_0123456789abcdef', created_at: '2026-10-24T19:00:00+00:00' }
  assert.equal(exampleText(ex), 'Sent to Mubit as a Line check example (request req_0123) · kind corrected')
  assert.equal(exampleText({ ...ex, kind: 'error', mubit_request_id: null }), 'Line check example not sent')
  assert.equal(exampleText(null), null)
  for (const ex2 of [ex, { ...ex, kind: 'matched' as const }]) assert.doesNotMatch(exampleText(ex2)!, /updated|serves|trained/)
})

test('the held-out row says Line check beside the rules in counts, never a percentage (#317)', () => {
  // the shape eval/linecheck_eval.py --json writes; tests/test_linecheck_live.py serves the same file
  const h: HeldOut = JSON.parse(readFileSync(new URL('../../tests/fixtures/linecheck_heldout.json', import.meta.url), 'utf8'))
  assert.equal(heldoutRow(h), 'held-out: caught 3 of 5 wrong lines (rules: 1 of 5), 5 false alarms')
  assert.equal(heldoutRow({ ...h, line_check: { caught: 3, false_alarms: 1 } })?.endsWith('1 false alarm'), true)
  assert.equal(heldoutRow(null), null)
  assert.equal(heldoutRow(undefined), null)
  for (const text of [heldoutRow(h) ?? '', FLAG_NOTE]) {
    assert.doesNotMatch(text, /%|adapter|serv|pass/i)
  }
  assert.match(FLAG_NOTE, /fix queue/)
  assert.match(FLAG_NOTE, /never unsays/)
})
