import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { adapterText, autonomyRows, checkText, consoleRow, earlierRows, exampleText, FALLBACK_NOTE, FLAG_NOTE, heldoutRow, linecheckRow, scoreCheckRows, scoreExampleLabel, TRAINING_LABEL, trainingHeading, voiceRow } from './proof.ts'
import type { ConsoleReading, HeldOut, ScoreCheckStats } from './types.ts'

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

// /stats' Score check block (#363), as live on 24 Oct with nothing yet read off the console
const block: ScoreCheckStats = {
  examples_sent: 2101,
  by_source: { answer_key: 2101, auto_fixed: 0, human: 0 },
  from_fixes_by_kind: {},
  held_out: { 'Claude Sonnet 5.5 via Mubit, unrecorded': { agree: 74, scored: 74, unparsed: 0, recorded_at: '2026-10-24T20:09:20+00:00' } },
  next_training: 'after 01:00 UK',
  recorded: null,
}

test("Score check is the card's one Mubit block: examples by source, the held-out baseline, its version and the next training (#363)", () => {
  assert.deepEqual(scoreCheckRows(block), [
    'Score check: no version recorded yet',
    'Examples sent: 2,101 (2,101 from the answer key, 0 auto-fixed, 0 by a person)',
    'Held-out (lines never sent): Claude Sonnet 5.5 via Mubit, unrecorded, 74 of 74 match the data',
    'Next training: after 01:00 UK',
  ])
  assert.deepEqual(scoreCheckRows({ ...block, recorded: { ...record, state: 'collecting', kept: 0 } })[0], 'Score check: collecting, 0 kept')
  for (const row of scoreCheckRows(block)) assert.doesNotMatch(row, /serves|passed|updated|Collecting/i)
})

test("the commentary tasks fold into one earlier-tasks list, still in their own words (#363)", () => {
  const earlier = {
    adapter: { state: 'collecting' as const, summary: 'Collecting: no adapter version recorded.', kept: null, agree: null, total: null, cost_measurable: false, console: null },
    adapters: { commentary: { ...record, state: 'collecting' as const }, where_are_we: { ...record, version: 1, score: 55.8, target: 95, passed: false } },
  }
  assert.deepEqual(earlierRows(earlier), [
    'Commentary: Collecting: no adapter version recorded.',
    'where are we: v1, 55.8%, below 95% target',
  ])
  const c: ConsoleReading = JSON.parse(readFileSync(new URL('../../data/mubit_console.json', import.meta.url), 'utf8'))
  const rows = earlierRows({ ...earlier, adapter: { ...earlier.adapter, console: c } })
  assert.deepEqual(rows.slice(1, 3), [consoleRow(c), consoleRow(c.earlier)])
  assert.deepEqual(earlierRows(undefined), [])
})

test("a failed gate in the console's words; a ready version with no verdict never reads as passed", () => {
  const sc = (a: Partial<typeof record>) => scoreCheckRows({ ...block, recorded: { ...record, ...a } })[0]
  assert.equal(sc({ version: 1, score: 55.8, target: 95, passed: false }), 'Score check: v1, 55.8%, below 95% target')
  // a failed verdict the score doesn't explain stays "Failed": no score, a score at the target, a 0 target
  const failed = { version: 1, passed: false, target: 95 }
  assert.equal(sc({ ...failed, score: null }), 'Score check: v1, Failed')
  assert.equal(sc({ ...failed, score: 95 }), 'Score check: v1, 95%, Failed')
  assert.equal(sc({ ...failed, score: 0, target: 0 }), 'Score check: v1, 0%, Failed')
  assert.equal(sc({ version: 3, score: 64.5 }), 'Score check: v3, 64.5%, verdict not recorded')
  assert.equal(sc({ state: 'collecting' }), 'Score check: collecting')
})

test('before core reports Score check, no rows', () => {
  assert.deepEqual(scoreCheckRows(undefined), [])
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

test("Score check's row keeps its earlier version, where it was read, and its examples and held-out scores (#321)", () => {
  const v1 = { version: 1, version_id: 'ad_1', score: 88.5, target: 95, passed: false, recorded_at: null, source: null }
  const v2 = { ...v1, version: 2, version_id: 'ad_2', score: 96, passed: true }
  const sc = { ...record, version: 2, version_id: 'ad_2', score: 96, target: 95, passed: true, state: 'passed' as const, source: 'Mubit console', versions: [v1, v2] }
  const rows = scoreCheckRows({
    ...block,
    examples_sent: 152,
    by_source: { answer_key: 150, auto_fixed: 0, human: 2 },
    from_fixes_by_kind: { corrected: 2 },
    held_out: { 'Claude Sonnet 5.5 via API': { agree: 70, scored: 74, unparsed: 0, recorded_at: null } },
    recorded: sc,
  })
  assert.deepEqual(rows, [
    'Score check: v2 (ad_2), 96%, Passed · before: v1, 88.5%, below 95% target · Mubit console, 2026-10-24 16:00 UTC',
    'Examples sent: 152 (150 from the answer key, 0 auto-fixed, 2 by a person: 2 corrected)',
    'Held-out (lines never sent): Claude Sonnet 5.5 via API, 70 of 74 match the data',
    'Next training: after 01:00 UK',
  ])
  for (const row of rows) assert.doesNotMatch(row, /serves|learns live|updated/)
})

test('the held-out row says Line check beside the rules in counts, never a percentage (#317)', () => {
  // the committed result /stats serves (core/stats.py HELDOUT), the README's source too: a rerun fails this
  const h: HeldOut = JSON.parse(readFileSync(new URL('../../eval/linecheck_heldout.json', import.meta.url), 'utf8'))
  assert.equal(heldoutRow(h), 'held-out: caught 3 of 5 wrong lines (rules: 2 of 5), 3 false alarms')
  assert.equal(heldoutRow({ ...h, line_check: { caught: 3, false_alarms: 1 } })?.endsWith('1 false alarm'), true)
  assert.equal(heldoutRow(null), null)
  assert.equal(heldoutRow(undefined), null)
  for (const text of [heldoutRow(h) ?? '', FLAG_NOTE]) {
    assert.doesNotMatch(text, /%|adapter|serv|pass/i)
  }
  assert.match(FLAG_NOTE, /fix queue/)
  assert.match(FLAG_NOTE, /never unsays/)
})

test("the console rows are the committed readings, dated and sourced, and claim no adapter serves (#317)", () => {
  const latest: ConsoleReading = JSON.parse(readFileSync(new URL('../../data/mubit_console.json', import.meta.url), 'utf8'))
  assert.equal(consoleRow(latest), 'Mubit console, 25 Oct 06:27 UTC: 12 tasks, 9 adapters; best 94.6%, Testing')
  const c = latest.earlier!
  const row = consoleRow(c) ?? ''
  assert.equal(row, 'Mubit console, 25 Oct 00:14 UTC: 11 tasks, 8 adapters, 0 serving; best 58.3% of a 95% target, Not ready yet')
  for (const r of [row, consoleRow(latest) ?? '']) assert.doesNotMatch(r, /pass|live|serv(es|ing [1-9])/i)
  assert.equal(consoleRow({ ...c, listed: {} }), 'Mubit console, 25 Oct 00:14 UTC: 11 tasks, 8 adapters, 0 serving')
  assert.equal(consoleRow(null), null)
  assert.equal(consoleRow(undefined), null)
})

test("a fix's training panel names each Score check example by its text and the data's label (#400)", () => {
  const fix = { corrected_text: 'Kobe has 2 points.' }
  const ex = { line_id: 'w', text: 'Kobe has 4 points.', gold: 'wrong' as const, kind: 'corrected' as const, mubit_request_id: 'r1', created_at: '' }
  assert.equal(scoreExampleLabel(ex, fix), 'Line as said: wrong')
  assert.equal(scoreExampleLabel({ ...ex, text: fix.corrected_text, gold: 'ok' }, fix), 'Fixed text: ok')
  assert.equal(scoreExampleLabel({ ...ex, gold: 'not_said' }, fix), 'Line as said: not said')
})

test('the panel shows the latest Score check adapter version, else that the training run is pending (#400)', () => {
  assert.equal(adapterText(undefined), 'Training run pending')
  assert.equal(adapterText({ recorded: null } as unknown as ScoreCheckStats), 'Training run pending')
  assert.equal(adapterText({ recorded: { ...record, version: 2 } } as unknown as ScoreCheckStats), 'Latest Score check adapter: v2')
  for (const t of [adapterText(undefined), adapterText({ recorded: { ...record, version: 2 } } as unknown as ScoreCheckStats)])
    assert.doesNotMatch(t, /updated|learns live/)
})

test("the training panel's heading claims a send only once the fix's own receipt says so (#400)", () => {
  assert.equal(trainingHeading('sent'), 'Sent to training')
  for (const s of ['pending', 'none', 'held_out', 'failed', 'unknown'] as const) assert.doesNotMatch(trainingHeading(s), /^Sent/)
})
