import assert from 'node:assert/strict'
import { test } from 'node:test'
import { fresh, release, replayClock, speaks } from './gate.ts'
import { Floor, type Turn } from './turns.ts'

test('with no video, the replay clock runs from the start second and releases each line on time', () => {
  let ms = 1000
  const clock = replayClock(485, () => ms)
  const lines = [{ video_t: 490 }, { video_t: 508 }]
  assert.deepEqual(clock(), { t: 485, playing: true, duration: 0 })
  assert.equal(release(lines, clock().t).live.length, 0)
  ms += 5000
  assert.deepEqual(release(lines, clock().t).live, [{ video_t: 490 }])
  ms += 18000
  assert.deepEqual(release(lines, clock().t).live, [{ video_t: 508 }])
})

test('a line a jump brought from an earlier replay is shown but never spoken, nor is a late one (#163)', () => {
  assert.equal(speaks({ line_id: 'a' }, []), true)
  assert.equal(speaks({ line_id: 'a', history: false }, []), true)
  assert.equal(speaks({ line_id: 'a', history: true }, []), false)
  assert.equal(speaks({ line_id: 'a' }, ['a']), false)
})

// build-233: the idx 3 Field goal call and its analyst fill landed in one render; only the newest was said.
test('two lines presented in one render are both handed on, oldest first, and a fill never costs the call', () => {
  const call = { line_id: 'call' }
  const fill = { line_id: 'fill', fill: true }
  const seen = new Set<string>()
  const batch = fresh([fill, call], seen, []) // newest first, as state.lines holds them
  assert.deepEqual(batch.map((l) => l.line_id), ['call', 'fill'])
  assert.deepEqual(fresh([fill, call], seen, []), []) // said once
  const floor = new Floor<Turn & { id: string }>()
  const say = [
    floor.take({ id: 'call', speaker: 'lead', big: true }, 0),
    floor.take({ id: 'fill', speaker: 'analyst', fill: true }, 0),
  ]
  assert.deepEqual(say, [true, false]) // the call goes on air; the fill is dropped, not queued ahead of it
})

test('a late or history line is skipped but still counted as seen', () => {
  const seen = new Set<string>()
  const lines = [{ line_id: 'b' }, { line_id: 'a', history: true }]
  assert.deepEqual(fresh(lines, seen, ['b']), [])
  assert.deepEqual(fresh([...lines, { line_id: 'c' }], seen, ['b']).map((l) => l.line_id), ['c'])
})
