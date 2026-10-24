import assert from 'node:assert/strict'
import { test } from 'node:test'
import { answerFor, names, recordLine, sampleNote, search, tonightLine, type Player, type Profile } from './follow.ts'
import type { Moment } from './types.ts'

const p = (name: string, team: string): Player => ({ name, team, record: true, named: false })
const players = [p('Kylian Mbappé', 'France'), p('Lionel Messi', 'Argentina'), p('Ángel Di María', 'Argentina')]

test('the picker finds a player without accents, by any word of the name or the team', () => {
  assert.deepEqual(search(players, 'mbappe').map((x) => x.name), ['Kylian Mbappé'])
  assert.deepEqual(search(players, 'angel di').map((x) => x.name), ['Ángel Di María'])
  assert.deepEqual(search(players, 'argentina').map((x) => x.name), ['Lionel Messi', 'Ángel Di María'])
  assert.equal(search(players, '').length, 3) // an empty box lists everyone, in the server's order
  assert.deepEqual(search(players, 'nobody'), [])
})

test("a line is the followed player's when its moment names them, in any role or F1's top five", () => {
  const m = (players: Record<string, string>, top?: { driver: string }[]) => ({ players, score: { top } }) as unknown as Moment
  assert.equal(names(m({ shooter: 'Kylian Mbappé' }), 'Kylian Mbappé'), true)
  assert.equal(names(m({ keeper: 'Hugo Lloris', shooter: 'Lionel Messi' }), 'Hugo Lloris'), true)
  assert.equal(names(m({ shooter: 'Lionel Messi' }), 'Kylian Mbappé'), false)
  assert.equal(names(m({}, [{ driver: 'Max Verstappen' }]), 'Max Verstappen'), true)
  assert.equal(names(m({ shooter: 'Lionel Messi' }), null), false)
  assert.equal(names(undefined, 'Lionel Messi'), false)
})

const base = { player: 'X', team: 'T', window: { from: '', to: '' }, n: 27, small_sample: false, text: '' }

test("the card's lines follow the sport", () => {
  const messi = { ...base, sport: 'football', before: { games: 6, attempts: 27, made: 5, xg: 4.57 }, tonight: { attempts: 3, made: 1, xg: 0.94 } } as Profile
  assert.equal(recordLine(messi), '5 goals from 27 shots, 4.57 xG in 6 games')
  assert.equal(tonightLine(messi), '1 goal from 3 shots, 0.94 xG')
  const kobe = { ...base, sport: 'basketball', before: { games: 38, attempts: 1036, made: 461 }, tonight: { attempts: 46, made: 28 } } as Profile
  assert.equal(recordLine(kobe), '461 of 1036 (44%) in 38 games')
  assert.equal(tonightLine(kobe), '28 of 46 (61%)')
  const ph = (balls: number, runs: number) => ({ powerplay: { balls, runs, outs: 0 }, middle: { balls: 0, runs: 0, outs: 0 }, death: { balls: 0, runs: 0, outs: 0 } })
  const kohli = { ...base, sport: 'cricket', before: { games: 13, batting: ph(287, 363), bowling: { balls: 0, runs: 0, wickets: 0, economy: null } }, tonight: { batting: ph(53, 82), bowling: { balls: 0, runs: 0, wickets: 0 } } } as Profile
  assert.equal(recordLine(kohli), '363 runs off 287 balls in 13 games')
  assert.equal(tonightLine(kohli), '82 off 53')
  const max = { ...base, sport: 'f1', before: { games: 20, wins: 7, finishes: 19, avg_finish: 2.9 }, tonight: { laps: [{ lap: 28, pos: 5 }, { lap: 69, pos: 1 }] } } as Profile
  assert.equal(recordLine(max), '7 wins in 20 races, average finish 2.9')
  assert.equal(tonightLine(max), 'P1 on lap 69')
  assert.equal(tonightLine({ ...max, tonight: { laps: [] } }), 'Not in the top five yet')
})

test('a small or missing record says so', () => {
  const thuram = { ...base, sport: 'football', n: 1, small_sample: true, before: { games: 4, attempts: 1, made: 0, xg: 0.12 }, tonight: {} } as Profile
  assert.equal(sampleNote(thuram), 'Small sample: 1 shot before tonight')
  assert.equal(sampleNote({ ...thuram, small_sample: false }), null)
  assert.equal(sampleNote({ ...thuram, before: null }), 'No pre-match record: tonight only')
})

test('a late answer never shows after a rewind, a player switch or a replay switch', () => {
  const got = { replay: 1, name: 'Lionel Messi', momentIdx: 34, value: 'messi@34' }
  assert.equal(answerFor(got, 1, 'Lionel Messi', 34), 'messi@34')
  assert.equal(answerFor(got, 1, 'Lionel Messi', 40), 'messi@34') // the next answer is on its way: never a spoiler
  assert.equal(answerFor(got, 1, 'Lionel Messi', 5), 'loading') // rewound before it: its stats are from later
  assert.equal(answerFor(got, 1, 'Kylian Mbappé', 34), 'loading') // followed someone else meanwhile
  assert.equal(answerFor(got, 2, 'Lionel Messi', 34), 'loading') // a new replay, even of the same match
  assert.equal(answerFor(null, 1, 'Lionel Messi', 34), 'loading')
  assert.equal(answerFor({ ...got, value: 'error' }, 1, 'Lionel Messi', 34), 'error')
})
