import assert from 'node:assert/strict'
import { test } from 'node:test'
import { momentOf, sameMoment } from './moment.ts'

// India v Pakistan as served: the cold open, the first ball's wicket and the analyst's stat all have idx 0.
const open = { idx: 0, type: 'Stat', score: { runs: 0, wickets: 0 } }
const wicket = { idx: 0, type: 'Wicket', video_t: 9, score: { runs: 1, wickets: 1 } }
const stat = { idx: 0, type: 'Stat', video_t: 10.78, score: { runs: 1, wickets: 1 } }

test('the first ball is its own moment, not the cold open with its idx', () => {
  assert.equal(sameMoment(open, wicket), false)
  assert.equal(sameMoment(wicket, stat), false)
  assert.equal(sameMoment(wicket, { ...wicket }), true) // a reconnect sends it again: still dropped
})

test('a line finds the moment it was said over', () => {
  const moments = [open, wicket, stat]
  assert.equal(momentOf(moments, { moment_idx: 0, video_t: 9 }), wicket)
  assert.equal(momentOf(moments, { moment_idx: 0, video_t: 10.78 }), stat)
  assert.equal(momentOf(moments, { moment_idx: 0 }), open)
  assert.equal(momentOf(moments, { moment_idx: 0, video_t: 99 }), open) // a jump's history line: its idx alone
})
