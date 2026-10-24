import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formLine, gameLine } from './teamfacts.ts'

const g = (result: string, score = '2-1') => ({ date: '2016-04-20', opponent: 'Everton', home: true, score, result })

test('form reads as a short sentence', () => {
  assert.equal(formLine('Orlando Pride', [g('W'), g('W'), g('W'), g('L'), g('L')]), 'Orlando Pride: won 3, lost 2 of their last 5')
  assert.equal(formLine('Chelsea', [g('W'), g('D')]), 'Chelsea: won 1, drew 1 of their last 2')
  assert.equal(formLine('Chelsea', []), 'Chelsea: no recent games on record')
})

test('a game names result, score, venue, opponent and date', () => {
  assert.equal(gameLine(g('W')), 'Won 2-1 at home against Everton, 20 April 2016')
  assert.equal(gameLine({ ...g('L', '0-3'), home: false }), 'Lost 0-3 away against Everton, 20 April 2016')
})
