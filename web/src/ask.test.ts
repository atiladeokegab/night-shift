import assert from 'node:assert/strict'
import { test } from 'node:test'
import { withAnswers } from './ask.ts'

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
