import assert from 'node:assert/strict'
import { test } from 'node:test'
import { listen, NO_MIC, NO_SPEECH, recognizer, type Recognizer } from './voice.ts'

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
