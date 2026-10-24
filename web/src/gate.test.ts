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

// Lakers v Raptors at speed 4 (24 Oct): Kobe's first basket and the analyst's stat after it were presented in one
// render, and only the newest (the stat) was spoken, so the big call was never heard.
test('two lines presented together are both handed on, oldest first, and the big call takes the air', () => {
  const open = { line_id: 'open', speaker: 'lead' as const }
  const kobe = { line_id: 'kobe', speaker: 'lead' as const, big: true }
  const stat = { line_id: 'stat', speaker: 'analyst' as const, fill: true }
  const seen = new Set(['open'])
  const batch = fresh([stat, kobe, open], seen, [])
  assert.deepEqual(batch.map((l) => l.line_id), ['kobe', 'stat'])

  const floor = new Floor<Turn & { line_id: string }>()
  const heard = [open, ...batch].filter((l) => floor.take(l, 0)).map((l) => l.line_id)
  assert.deepEqual(heard, ['open', 'kobe']) // the call cuts in on the routine open; a fill never waits, so the stat goes
  assert.equal(floor.cut, null) // the stat cut nothing
})

test('nothing is handed on twice, and a new replay starts from none', () => {
  const seen = new Set<string>()
  assert.deepEqual(fresh([{ line_id: 'a' }], seen, []).map((l) => l.line_id), ['a'])
  assert.deepEqual(fresh([{ line_id: 'a' }], seen, []), [])
  seen.clear() // what useReplay does when a new replay empties the lines
  assert.deepEqual(fresh([{ line_id: 'a' }], seen, []).map((l) => l.line_id), ['a'])
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

// Live, Lakers-Raptors at speed 4: ~12 lines for one moment arrive within 0.3 s.
test('in a burst every big call is said, in order, and only fills are dropped', () => {
  type T = Turn & { id: string }
  const burst: T[] = []
  for (let i = 0; i < 12; i++) {
    burst.push(i % 3 === 0 ? { id: `call${i}`, speaker: 'lead', big: true } : { id: `fill${i}`, speaker: 'analyst', fill: true })
  }
  const floor = new Floor<T>()
  const said: string[] = []
  let on: T | null = null
  for (const t of burst) if (floor.take(t, 0)) {
      on = on ?? t
      said.push(t.id)
    }
  while (on) {
    on = floor.ended(on, 1)
    if (on) said.push(on.id)
  }
  assert.deepEqual(said, ['call0', 'call3', 'call6', 'call9']) // every call, in order; no fill
})
