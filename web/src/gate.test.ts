import assert from 'node:assert/strict'
import { test } from 'node:test'
import { release, replayClock } from './gate.ts'

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
