import assert from 'node:assert/strict'
import { test } from 'node:test'
import { viewOf } from './view.ts'

test('every screen change and every new match is a new view, so the page opens at the top', () => {
  const wall = viewOf('wall', undefined)
  const first = viewOf('live', 1)
  const next = viewOf('live', 2)
  assert.equal(new Set([wall, first, next, viewOf('picker', undefined), viewOf('about', undefined)]).size, 5)
  // A re-render of the same match (a new line, the voice sheet) is not a new view: no jump to the top mid-match.
  assert.equal(viewOf('live', 2), next)
})
