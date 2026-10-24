import assert from 'node:assert/strict'
import { test } from 'node:test'
import { QUIET_MS, QuietSpell } from './quiet.ts'

test('a quiet spell fires once, and the next line starts a new one', () => {
  const q = new QuietSpell()
  assert.equal(q.due(QUIET_MS - 1, true), false)
  assert.equal(q.due(QUIET_MS, true), true)
  assert.equal(q.due(QUIET_MS + 1, true), false) // once per spell, however long it lasts
  assert.equal(q.due(5 * QUIET_MS, true), false)
  q.said(5 * QUIET_MS)
  assert.equal(q.due(6 * QUIET_MS - 1, true), false)
  assert.equal(q.due(6 * QUIET_MS, true), true)
})

test('time off play does not count toward a quiet spell', () => {
  const q = new QuietSpell()
  assert.equal(q.due(QUIET_MS - 1000, true), false)
  assert.equal(q.due(QUIET_MS + 5000, false), false) // paused: the spell starts again on play
  assert.equal(q.due(2 * QUIET_MS, true), false)
  assert.equal(q.due(2 * QUIET_MS + 5000, true), true)
})
