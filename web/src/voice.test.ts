import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isViewer, listen, listenAlways, MIC_FAILED, NO_MIC, NO_SPEECH, recognizer, type Recognizer } from './voice.ts'

class Fake implements Recognizer {
  lang = ''
  interimResults = false
  continuous = true
  onresult: Recognizer['onresult'] = null
  onerror: Recognizer['onerror'] = null
  onend: Recognizer['onend'] = null
  started = false
  stopped = false
  start() {
    this.started = true
  }
  stop() {
    this.stopped = true
  }
  say(final: boolean, ...words: string[]) {
    const results = words.map((transcript, i) => Object.assign([{ transcript }], { isFinal: final && i === words.length - 1 }))
    this.onresult?.({ results })
  }
}

const record = () => {
  const got: string[] = []
  return { got, on: { heard: (t: string) => got.push(`heard ${t}`), done: (t: string) => got.push(`done ${t}`), hint: (t: string) => got.push(`hint ${t}`) } }
}

test('interim words show as the viewer talks, and the final result sends them once', () => {
  const fake = new Fake()
  const { got, on } = record()
  listen(() => fake, on)
  assert.ok(fake.started)
  assert.equal(fake.lang, 'en-GB')
  assert.ok(fake.interimResults)
  fake.say(false, 'who')
  fake.say(false, 'who scores', ' next')
  fake.say(true, 'who scores', ' next?')
  fake.onend?.()
  assert.deepEqual(got, ['heard who', 'heard who scores next', 'done who scores next?'])
})

test('releasing the button sends what was heard so far', () => {
  const fake = new Fake()
  const { got, on } = record()
  const release = listen(() => fake, on)
  fake.say(false, "what's the score")
  release()
  assert.ok(fake.stopped)
  fake.onend?.() // the browser ends the session after stop()
  assert.deepEqual(got, ["heard what's the score", "done what's the score"])
})

test('a denied mic or nothing heard leaves a one-line hint, never a send', () => {
  for (const [error, hint] of [['not-allowed', NO_MIC], ['no-speech', NO_SPEECH]]) {
    const fake = new Fake()
    const { got, on } = record()
    listen(() => fake, on)
    fake.onerror?.({ error })
    fake.onend?.()
    assert.deepEqual(got, [`hint ${hint}`])
  }
  const silent = new Fake()
  const { got, on } = record()
  listen(() => silent, on)
  silent.onend?.() // released before a word
  assert.deepEqual(got, [`hint ${NO_SPEECH}`])
  const busy = new Fake()
  busy.start = () => {
    throw new Error('InvalidStateError')
  }
  const failed = record()
  listen(() => busy, failed.on)
  assert.deepEqual(failed.got, [`hint ${NO_MIC}`])
})

test('the mic is hidden where the browser has no speech recognition', () => {
  assert.equal(recognizer(), null)
  const g = globalThis as Record<string, unknown>
  g.webkitSpeechRecognition = Fake
  try {
    assert.ok(recognizer()?.() instanceof Fake)
  } finally {
    delete g.webkitSpeechRecognition
  }
})

const always = () => {
  const fakes: Fake[] = []
  const got: string[] = []
  const on = { ...record().on, barge: () => got.push('barge') }
  for (const k of ['heard', 'done', 'hint'] as const) on[k] = (t: string) => got.push(`${k} ${t}`)
  return { fakes, got, on, make: () => (fakes.push(new Fake()), fakes[fakes.length - 1]) }
}

test('Mic on starts the recognizer again after the browser ends it, until it is turned off', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'] })
  const { fakes, got, on, make } = always()
  const stop = listenAlways(make, on, () => null)
  assert.equal(fakes.length, 1)
  assert.ok(fakes[0].started)
  t.mock.timers.tick(5000)
  fakes[0].onend?.() // Chrome stops after a silence
  t.mock.timers.tick(0)
  assert.equal(fakes.length, 2)
  assert.ok(fakes[1].started)
  fakes[1].onend?.() // ended at once: wait a second, never spin
  t.mock.timers.tick(999)
  assert.equal(fakes.length, 2)
  t.mock.timers.tick(1)
  assert.equal(fakes.length, 3)
  stop()
  assert.ok(fakes[2].stopped)
  fakes[2].onend?.()
  t.mock.timers.tick(5000)
  assert.equal(fakes.length, 3, 'off stays off')
  assert.deepEqual(got, [])
})

test("Mic on never sends the page's own line back, and sends the viewer's question once", () => {
  const { fakes, got, on, make } = always()
  const line = 'Michael Jordan with the driving layup, forty-three for him! Utah still lead, eighty-six to eighty-five.'
  let onAir: string | null = line
  listenAlways(make, on, () => onAir)
  fakes[0].say(false, 'Michael Jordan with the')
  fakes[0].say(true, 'Michael Jordan with the driving layup forty three for him')
  fakes[0].say(false, 'who') // under 3 words while a line is on air: could be the line
  assert.deepEqual(got, [], 'an echo is neither shown, sent nor a barge-in')
  fakes[0].say(false, 'who leads the')
  fakes[0].say(true, 'who leads the scoring tonight')
  assert.deepEqual(got, ['barge', 'heard who leads the', 'done who leads the scoring tonight'])
  onAir = null // nothing on air: one word is the viewer
  fakes[0].say(true, 'score?')
  assert.deepEqual(got.slice(3), ['barge', 'done score?'])
})

test('Mic on turns itself off with the hint when the mic is denied', () => {
  for (const [error, hint] of [['not-allowed', NO_MIC], ['network', MIC_FAILED]]) {
    const { fakes, got, on, make } = always()
    listenAlways(make, on, () => null)
    fakes[0].onerror?.({ error })
    fakes[0].onend?.()
    assert.deepEqual(got, [`hint ${hint}`])
    assert.equal(fakes.length, 1)
  }
  const { fakes, got, on, make } = always()
  listenAlways(make, on, () => null)
  fakes[0].onerror?.({ error: 'no-speech' }) // a silence: keep listening
  assert.deepEqual(got, [])
})

test('isViewer: a question that shares a word with the line is still the viewer', () => {
  assert.ok(isViewer('who scored that goal', 'Goal! Salah scores at the far post.'))
  assert.ok(!isViewer('Salah scores at the far post', 'Goal! Salah scores at the far post.'))
  assert.ok(!isViewer('', null))
})
