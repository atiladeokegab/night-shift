import assert from 'node:assert/strict'
import { test } from 'node:test'
import { answeredAt, isStale, withAnswers } from './ask.ts'
import type { Moment } from './types.ts'

const line = (idx: number) => ({ line_id: `l${idx}`, match_id: 'm', moment_idx: idx, text: `line ${idx}`, latency_ms: 1 })
const answer = (id: string, idx: number) => ({ line_id: id, moment_idx: idx, question: '?', text: 'a' })

test('each answer sits above the lines up to its moment, newest first', () => {
  const lines = [line(3), line(2), line(1)]
  const answers = [answer('later', 2), answer('first', 1), answer('again', 2)]
  const ids = withAnswers(lines, answers).map((x) => x.line?.line_id ?? x.answer!.line_id)
  assert.deepEqual(ids, ['l3', 'later', 'again', 'l2', 'first', 'l1'])
})

test('answers with no lines yet still show', () => {
  assert.deepEqual(withAnswers([], [answer('a', 0)]).map((x) => x.answer?.line_id), ['a'])
})

const at = (idx: number, clock: string, sport: Moment['sport'] = 'football') =>
  ({ sport, match_id: 'm', idx, period: 2, clock, type: 'Shot', score: { home: 3, away: 3 }, detail: {} }) as Moment

test("an answer carries its own time, from the moment it was asked at", () => {
  const moments = [at(66, '104:30'), at(67, '105:41')]
  assert.equal(answeredAt(answer('a', 66), moments), 'at 104:30')
  assert.equal(answeredAt(answer('a', 5), [at(5, '12.3', 'cricket')]), 'at Over 12.3')
  assert.equal(answeredAt(answer('a', 9), moments), null) // its moment isn't on screen: no time is guessed
})

test('an answer goes stale once a later key moment is on screen, never before', () => {
  assert.equal(isStale(answer('a', 66), [at(65, '103:00'), at(66, '104:30')]), false)
  assert.equal(isStale(answer('a', 66), [at(66, '104:30'), at(67, '105:41')]), true)
})
