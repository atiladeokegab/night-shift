import assert from 'node:assert/strict'
import { test } from 'node:test'
import { presentedSince, release, replayClock, speaks } from './gate.ts'
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

// Lakers v Raptors at speed 4 (24 Oct): Kobe's first basket and the analyst's stat after it were presented in one
// render, and only the newest (the stat) was spoken, so the big call was never heard.
test('two lines presented together are both handed on, oldest first, and the big call takes the air', () => {
  const open = { line_id: 'open', speaker: 'lead' as const }
  const kobe = { line_id: 'kobe', speaker: 'lead' as const, big: true }
  const stat = { line_id: 'stat', speaker: 'analyst' as const, fill: true }
  const fresh = presentedSince([stat, kobe, open], [open])
  assert.deepEqual(fresh.map((l) => l.line_id), ['kobe', 'stat'])

  const floor = new Floor<Turn & { line_id: string }>()
  const heard = [open, ...fresh].filter((l) => floor.take(l, 0)).map((l) => l.line_id)
  assert.deepEqual(heard, ['open', 'kobe']) // the call cuts in on the routine open; a fill never waits, so the stat goes
  assert.equal(floor.cut, null) // the stat cut nothing
})

test('nothing is handed on twice, and a new replay starts from none', () => {
  assert.deepEqual(presentedSince([{ line_id: 'a' }], [{ line_id: 'a' }]), [])
  assert.deepEqual(presentedSince([{ line_id: 'a' }], []), [{ line_id: 'a' }])
})
