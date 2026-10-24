import assert from 'node:assert/strict'
import { test } from 'node:test'
import { latestShooter, place } from './shots.ts'
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
