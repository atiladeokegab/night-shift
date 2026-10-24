import assert from 'node:assert/strict'
import { test } from 'node:test'
import { nextAdapter } from './proof.ts'

test('under the target, the figure counts toward it', () => {
  assert.deepEqual(nextAdapter(12, 25), { value: '12 of 25', note: null })
})

test('at or over the target, it never reads "66 of 25" and says there are enough', () => {
  const { value, note } = nextAdapter(66, 25)
  assert.doesNotMatch(value, / of /)
  assert.equal(note, '66 fixes recorded · 25 needed: enough for the next adapter')
  assert.equal(nextAdapter(25, 25).note, '25 fixes recorded · 25 needed: enough for the next adapter')
})
