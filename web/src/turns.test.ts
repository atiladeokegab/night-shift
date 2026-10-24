import assert from 'node:assert/strict'
import { test } from 'node:test'
import { airAnswer, Floor, HOLD_MAX_MS, isBig, voiceOf, type Caption, type Turn } from './turns.ts'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
type Said = Turn & { id: string }
const lead = (id: string, big = false): Said => ({ id, speaker: 'lead', big })
const analyst = (id: string): Said => ({ id, speaker: 'analyst' })

test('a line due while an answer is spoken waits for it, and is only shown once it is over 5 s late', () => {
  const floor = new Floor<Said>()
  const answer: Said = { id: 'answer', speaker: 'lead', answer: true }
  assert.equal(floor.take(answer, 0), true)
  assert.equal(floor.take(lead('shot'), 1000), false) // held: the answer is never cut off
  assert.equal(floor.take(lead('goal', true), 2000), false) // not even by a big moment; it replaces the held line
  const goal = floor.ended(answer, 2000 + HOLD_MAX_MS)
  assert.equal(goal?.id, 'goal') // 5 s late: still spoken, and it holds the floor now
  assert.equal(floor.ended(goal!, 8000), null)
  const again: Said = { id: 'again', speaker: 'lead', answer: true }
  floor.take(again, 10_000)
  floor.take(lead('corner'), 10_000)
  assert.equal(floor.ended(again, 10_001 + HOLD_MAX_MS), null) // over 5 s late: shown, never spoken
  assert.equal(floor.take(lead('save'), 20_000), true) // the floor is free again
})

test('the two commentators take turns, and only a big moment cuts in on the other one', () => {
  const floor = new Floor<Said>()
  const shot = lead('shot')
  const rebound = lead('rebound')
  assert.equal(floor.take(shot, 0), true)
  assert.equal(floor.take(rebound, 500), true) // the same speaker: the newer line cuts off the older
  assert.equal(floor.take(analyst('stat'), 1000), false) // the analyst never talks over the lead
  assert.equal(floor.ended(shot, 1200), null) // a line already cut off ends nothing
  assert.equal(floor.ended(rebound, 1500)?.id, 'stat') // the analyst's turn comes when the lead stops
  const stats = new Floor<Said>()
  const numbers = analyst('numbers')
  stats.take(numbers, 0)
  assert.equal(stats.take(lead('save'), 100), false) // a routine call waits for the analyst to finish
  assert.equal(stats.ended(numbers, 900)?.id, 'save')
  stats.take(analyst('more numbers'), 1000)
  assert.equal(stats.take(lead('goal', true), 1100), true) // a goal cuts in, like a real broadcast
  stats.clear() // a rewind, a pause or leaving drops the held line too
  assert.equal(stats.take(analyst('after'), 2000), true)
})

test('goals, wickets, baskets and overtakes are big; routine moments are not', () => {
  assert.ok(isBig({ type: 'Shot', outcome: 'Goal' }))
  assert.ok(isBig({ type: 'Wicket', outcome: 'caught' }))
  assert.ok(isBig({ type: 'Field goal', outcome: '3 points' }))
  assert.ok(isBig({ type: 'Overtake', outcome: 'P3 on track' }))
  assert.ok(!isBig({ type: 'Shot', outcome: 'Saved' }))
  assert.ok(!isBig({ type: 'Four', outcome: '4 runs' }))
  assert.ok(!isBig(undefined))
})

test("each speaker has their own voice: the analyst follows the sport, the lead the viewer's pick", () => {
  assert.deepEqual(voiceOf('lead', 'connor'), { id: 'connor', pitch: 1, rate: 1.1 })
  const analystVoice = voiceOf('analyst', 'connor')
  assert.equal(analystVoice.id, undefined) // the server picks the sport's analyst voice
  assert.notEqual(analystVoice.pitch, 1) // the browser fallback still sounds like someone else
})

test('the stage shows the question, then the answer while it is spoken, then the lines again', async () => {
  const shown: (Caption | null)[] = []
  let answer!: (a: { text: string }) => void
  let spoken!: () => void
  const asking = airAnswer(
    'Who scores next?',
    () => new Promise((r) => (answer = r)),
    () => new Promise<void>((r) => (spoken = r)),
    (c) => shown.push(c),
    () => true,
  )
  assert.deepEqual(shown, [{ kind: 'question', text: 'A viewer asks: Who scores next?' }])
  answer({ text: 'Who scores next? Reds are pressing!' })
  await asking // the ask box is free once the answer is in, while it is still being spoken
  assert.deepEqual(shown.at(-1), { kind: 'answer', text: 'Who scores next? Reds are pressing!', speaker: 'lead' })
  spoken()
  await sleep(0)
  assert.equal(shown.at(-1), null)
})

test('an answer that is not spoken stays up for the read time; a replaced replay changes nothing', async () => {
  const shown: (string | null)[] = []
  await airAnswer('Score?', async () => ({ text: 'Off air' }), () => null, (c) => shown.push(c?.text ?? null), () => true, 20)
  assert.deepEqual(shown, ['A viewer asks: Score?', 'Off air'])
  await sleep(40)
  assert.equal(shown.at(-1), null)
  const stale: (string | null)[] = []
  let current = true
  const late = airAnswer('Score?', async () => ({ text: 'One nil' }), () => null, (c) => stale.push(c?.text ?? null), () => current)
  current = false // the viewer switched match before the answer came back
  await late
  assert.deepEqual(stale, ['A viewer asks: Score?'])
})
