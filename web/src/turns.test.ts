import assert from 'node:assert/strict'
import { test } from 'node:test'
import { airAnswer, bigSoon, Floor, HOLD_MAX_MS, isBig, VIEWER_MS, isDecisive, loudness, voiceOf, type Caption, type Turn } from './turns.ts'

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

test('turns wait for each other in order, the same speaker included: nothing is ever cut mid-line', () => {
  const floor = new Floor<Said>()
  const shot = lead('shot')
  assert.equal(floor.take(shot, 0), true)
  assert.equal(floor.take(lead('rebound'), 500), false) // the same speaker waits too
  assert.equal(floor.take(analyst('stat'), 1000), false)
  const rebound = floor.ended(shot, 1200)
  assert.equal(rebound?.id, 'rebound') // order kept
  assert.equal(floor.ended(rebound!, 1500)?.id, 'stat')
  const goals = new Floor<Said>()
  const numbers = analyst('numbers')
  goals.take(numbers, 0)
  assert.equal(goals.take(lead('save'), 100), false)
  assert.equal(goals.take(lead('goal', true), 200), false) // a goal waits for the turn on air...
  assert.equal(goals.ended(numbers, 900)?.id, 'goal') // ...then goes ahead of the routine call waiting
  goals.clear() // a rewind, a pause or leaving drops the held lines too
  assert.equal(goals.take(analyst('after'), 2000), true)
})
test('a question asked mid-line is answered when that line ends, and held back while a big moment is due', () => {
  const floor = new Floor<Said>()
  let due = false
  floor.bigDue = () => due
  const call = lead('call')
  const answer: Said = { id: 'answer', speaker: 'analyst', answer: true }
  floor.take(call, 0)
  assert.equal(floor.take(answer, 500), false) // mid-line: the commentary carries on
  assert.equal(floor.take(lead('more'), 800), false) // and the next line waits, never cutting in
  due = true
  const more = floor.ended(call, 900)
  assert.equal(more?.id, 'more') // a goal is due: the answer is held back
  assert.equal(floor.gap(), null)
  due = false
  assert.equal(floor.ended(more!, 1500)?.id, 'answer') // the goal has gone by: the answer takes the floor
})
test('a big moment is due when the picture reaches it within 3 s', () => {
  const goal = { type: 'Shot', outcome: 'Goal', video_t: 63 }
  assert.ok(bigSoon([goal], 61))
  assert.ok(!bigSoon([goal], 59)) // over 3 s away
  assert.ok(!bigSoon([goal], 64)) // already gone by
  assert.ok(!bigSoon([{ ...goal, outcome: 'Saved' }], 62)) // routine
  assert.ok(!bigSoon([{ type: 'Shot', outcome: 'Goal' }], 0)) // ungated: no time to know
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
  let start!: () => void
  const asking = airAnswer(
    'Who scores next?',
    () => new Promise((r) => (answer = r)),
    (_, started) => ((start = started), new Promise<void>((r) => (spoken = r))),
    (c) => shown.push(c),
    () => true,
  )
  assert.deepEqual(shown, [{ kind: 'question', text: 'A viewer asks: Who scores next? · thinking…' }])
  answer({ text: 'Who scores next? Reds are pressing!' })
  await asking // the ask box is free once the answer is in, while it waits for a gap and is spoken
  // answered, so no longer "thinking…": the question alone while the commentary goes on until a gap
  assert.deepEqual(shown.at(-1), { kind: 'question', text: 'A viewer asks: Who scores next?' })
  start()
  assert.deepEqual(shown.at(-1), { kind: 'answer', text: 'Who scores next? Reds are pressing!', speaker: 'analyst' })
  spoken()
  await sleep(0)
  assert.equal(shown.at(-1), null)
})

test('an answer that is not spoken stays up for the read time; a replaced replay changes nothing', async () => {
  const shown: (string | null)[] = []
  await airAnswer('Score?', async () => ({ text: 'Off air' }), () => null, (c) => shown.push(c?.text ?? null), () => true, 20)
  assert.deepEqual(shown, ['A viewer asks: Score? · thinking…', 'A viewer asks: Score?', 'Off air'])
  await sleep(40)
  assert.equal(shown.at(-1), null)
  const stale: (string | null)[] = []
  let current = true
  const late = airAnswer('Score?', async () => ({ text: 'One nil' }), () => null, (c) => stale.push(c?.text ?? null), () => current)
  current = false // the viewer switched match before the answer came back
  await late
  assert.deepEqual(stale, ['A viewer asks: Score? · thinking…'])
})

test('the commentary plays at the chosen volume, kept between 0 and 1, and muted is silent', () => {
  assert.equal(loudness(0.4, false), 0.4)
  assert.equal(loudness(1.5, false), 1)
  assert.equal(loudness(-1, false), 0)
  assert.equal(loudness(Number.NaN, false), 0)
  assert.equal(loudness(0.8, true), 0)
})

test('a decisive moment waits for the answer on air like any other turn', () => {
  const floor = new Floor<Said>()
  const answer: Said = { id: 'answer', speaker: 'analyst', answer: true }
  assert.equal(floor.take(answer, 0), true)
  const goal: Said = { id: 'goal', speaker: 'lead', big: true, decisive: true }
  assert.equal(floor.take(goal, 1000), false)
  assert.equal(floor.ended(answer, 4000)?.id, 'goal')
})
test('a goal, a wicket, a lead change and the final whistle are decisive; a basket or a six is not', () => {
  assert.equal(isDecisive({ type: 'Shot', outcome: 'Goal' }), true)
  assert.equal(isDecisive({ type: 'Own Goal Against', outcome: 'Own goal' }), true)
  for (const type of ['Wicket', 'Lead change', 'Full time', 'End of game']) assert.equal(isDecisive({ type, outcome: '' }), true, type)
  for (const type of ['Field goal', 'Six', 'Overtake', 'Shot']) assert.equal(isDecisive({ type, outcome: 'Saved' }), false, type)
  assert.equal(isDecisive(undefined), false)
})

test('a fill line in a quiet stretch never waits behind anything, so the next moment is never late (#297)', () => {
  const floor = new Floor<Said>()
  const aside: Said = { id: 'aside', speaker: 'lead', fill: true }
  assert.equal(floor.take(aside, 0), true)
  assert.equal(floor.take({ id: 'more', speaker: 'analyst', fill: true }, 3000), false) // dropped, not queued
  assert.equal(floor.take(lead('save'), 3500), false) // the moment waits for the aside to end
  assert.equal(floor.ended(aside, 4000)?.id, 'save') // and the extra fill line was never said after it
})
test('while the viewer talks and their answer waits, no fill line starts; a moment still does (#297)', () => {
  const floor = new Floor<Said>()
  const fill = (id: string): Said => ({ id, speaker: 'analyst', fill: true })
  floor.take(fill('on air'), 0)
  floor.clear() // Mic on heard the viewer: the line on air is hushed
  floor.viewer(1000)
  assert.equal(floor.take(fill('next'), 1500), false)
  assert.equal(floor.ended(fill('next'), 2000), null) // dropped, not held for later
  const call = lead('shot')
  assert.equal(floor.take(call, 2500), true) // the moment always wins
  assert.equal(floor.take(fill('after the call'), 5000), false)
  const answer: Said = { id: 'answer', speaker: 'analyst', answer: true }
  assert.equal(floor.take(answer, 6000), false) // the answer waits for the call to end
  assert.equal(floor.take(fill('while it waits'), 6500), false)
  assert.equal(floor.ended(call, 7000), answer) // the booth answers the viewer next
  assert.equal(floor.ended(answer, 9000), null)
  assert.equal(floor.take(fill('carry on'), 9500), true) // then they carry on
  const quiet = new Floor<Said>()
  quiet.viewer(0) // heard, but nothing was asked
  assert.equal(quiet.take(fill('soon'), VIEWER_MS - 1), false)
  assert.equal(quiet.take(fill('later'), VIEWER_MS), true)
  const slow = new Floor<Said>()
  slow.viewer(0)
  slow.take(lead('long call'), 500)
  slow.take(answer, 1000)
  const comeback: Said = { id: 'past the quiet', speaker: 'lead', fill: true }
  assert.equal(slow.take(comeback, VIEWER_MS + 1000), false) // the answer still waits: it goes first
})

test('a big moment waits for the turn on air to end, is not replaced by a routine line, and is never stale', () => {
  const floor = new Floor<Said>()
  const talk = analyst('talk')
  floor.take(talk, 0)
  assert.equal(floor.take(lead('goal', true), 100), false)
  assert.equal(floor.take(lead('routine'), 200), false) // does not replace the held goal
  assert.equal(floor.ended(talk, 100 + HOLD_MAX_MS * 2)?.id, 'goal') // late, still said
})

test('one turn on air at a time: every take that returns true cut off the previous one', () => {
  const floor = new Floor<Said>()
  let air = 0
  const take = (t: Said, now: number) => {
    if (floor.take(t, now)) air = 1 // play() stops the old sound first
    return air
  }
  for (const [i, t] of [lead('a'), analyst('b'), lead('c', true), analyst('d'), lead('e')].entries()) assert.equal(take(t, i * 100), 1)
})
