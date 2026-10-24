import assert from 'node:assert/strict'
import { test } from 'node:test'
import { latestShooter, pickedFor, place, zoneName } from './shots.ts'
import type { Moment } from './types.ts'

const m = (idx: number, players: Record<string, string>) => ({ idx, players }) as Moment

test('the map opens for the latest shooter on screen, past a card or a substitution', () => {
  assert.equal(latestShooter([m(0, { shooter: 'Kobe Bryant' }), m(1, { offender: 'Smush Parker' })]), 'Kobe Bryant')
  assert.equal(latestShooter([m(0, { shooter: 'A' }), m(1, { shooter: 'Lionel Messi' })]), 'Lionel Messi')
  assert.equal(latestShooter([m(0, { batter: 'Virat Kohli' })]), null)
  assert.equal(latestShooter([]), null)
})

test('a football shot turns to the attacking half, goal at the top; a basketball shot keeps LOC_X/LOC_Y', () => {
  assert.deepEqual(place('football', 120, 40), [40, 0]) // the goal's centre
  assert.deepEqual(place('football', 108, 30), [30, 12]) // level with the penalty spot, left of it
  assert.deepEqual(place('basketball', -220, 30), [-220, 30])
})

test('the paint zone fits one line at phone width; other zones keep their names', () => {
  assert.equal(zoneName('In The Paint (Non-RA)'), 'Paint (non-RA)')
  assert.equal(zoneName('Mid-Range'), 'Mid-Range')
})

test('a map picked in one replay never reopens in the next', () => {
  const picked = { name: 'Kobe Bryant', replay: 1 }
  assert.equal(pickedFor(picked, 1), 'Kobe Bryant')
  assert.equal(pickedFor(picked, 2), null) // a new match, or the same one started again
  assert.equal(pickedFor(null, 1), null)
})
