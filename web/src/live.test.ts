import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'rolldown/experimental'
import { setPlaying, shownCaption, type Transport } from './player.ts'
import type { Line, Match, Moment } from './types.ts'
import type { ReplayState } from './useReplay.ts'

// The live page rendered to HTML in node: .tsx goes through Vite's own transform, and the app's
// extensionless imports resolve as Vite resolves them.
registerHooks({
  resolve(specifier, context, next) {
    if (/^\.\.?\//.test(specifier) && !/\.[a-z]+$/.test(specifier)) {
      for (const ext of ['.ts', '.tsx']) {
        try {
          return next(specifier + ext, context)
        } catch {
          // not this extension
        }
      }
    }
    return next(specifier, context)
  },
  load(url, context, next) {
    if (!url.endsWith('.tsx')) return next(url, context)
    const { code } = transformSync(fileURLToPath(url), readFileSync(new URL(url), 'utf8'), { jsx: { runtime: 'automatic' } })
    return { format: 'module', source: code, shortCircuit: true }
  },
})
Object.assign(globalThis, { window: { location: { search: '' } } }) // api.ts reads ?demo on import
const { Live } = await import('./components/Live.tsx')

const match: Match = { match_id: '0020500591', sport: 'basketball', title: 'Los Angeles Lakers v Toronto Raptors, NBA Regular season', youtube_id: '46nYnjGdQlk', video_start: 480 }
const moment = (idx: number, video_t: number, clock: string): Moment => ({
  sport: 'basketball', match_id: match.match_id, idx, period: 3, clock, type: 'Field goal', team: 'Los Angeles Lakers',
  players: { shooter: 'Kobe Bryant' }, outcome: '2 points', score: { home: 60 + idx, away: 69 }, detail: {}, video_t,
})
const line = (idx: number, video_t: number, text: string): Line => ({ line_id: `l${idx}`, match_id: match.match_id, moment_idx: idx, text, latency_ms: 900, video_t })
const EARLY = 'Kobe pulls up from the elbow and buries it.'
const LATER = 'Kobe again! That is forty for the night.'

// Played to 510 s (both moments on screen), then sought back to 500 s: the 508 s moment is ahead again.
const replay: ReplayState = {
  phase: 'live', stream: 'ok', gated: true, now: 500, duration: 1671,
  moments: [moment(3, 490.5, '06:12'), moment(4, 508, '05:40')], lines: [line(4, 508, LATER), line(3, 490.5, EARLY)],
  late: [], queuedMoments: [], queuedLines: [], ended: false, error: null, refused: null, stats: null, fixes: {}, answers: [],
}

const noop = () => {}
function render(props: Record<string, unknown> = {}) {
  return renderToStaticMarkup(createElement(Live, {
    match, replay, replayKey: 1, switching: false, sports: ['football', 'basketball'],
    voice: { status: 'on', chip: 'Sam', speaking: true }, video: 'ok', onVideo: noop, onClock: noop, onSport: noop, onNext: null,
    onVoiceSheet: noop, onFix: noop, onAsk: async () => {}, onRetry: noop, onReconnect: noop, onGo: noop, ...props,
  }))
}

// The HTML from `<section class="vcard"` to its own closing tag.
function videoCard(html: string): string {
  const start = html.indexOf('<section class="vcard"')
  assert.ok(start >= 0, 'the video card is on the page')
  const tags = /<(\/?)section\b/g
  tags.lastIndex = start
  let depth = 0
  for (let m = tags.exec(html); m; m = tags.exec(html)) {
    depth += m[1] ? -1 : 1
    if (depth === 0) return html.slice(start, m.index)
  }
  throw new Error('the video card never closes')
}

test('pause holds the player and tells App, so the voice stops with the picture; play resumes both', () => {
  const calls: string[] = []
  const transport: Transport = { play: () => calls.push('player play'), pause: () => calls.push('player pause'), seek: noop }
  const on = { onPause: () => calls.push('onPause'), onPlay: () => calls.push('onPlay') }
  setPlaying(false, transport, on)
  assert.deepEqual(calls, ['player pause', 'onPause'])
  setPlaying(true, transport, on)
  assert.deepEqual(calls, ['player pause', 'onPause', 'player play', 'onPlay'])
  setPlaying(false, null, on) // no player yet: App still hears it
  assert.equal(calls.at(-1), 'onPause')
})

test('a seek backwards never shows a line from later than the new time (A-6.4)', () => {
  // App's caption is still the 508 s line it last spoke; the picture is back at 500 s.
  const html = render({ caption: { kind: 'line', text: LATER, speaker: 'lead' } })
  assert.ok(!html.includes(LATER), 'the later line is gone from the caption and the log')
  assert.match(html, new RegExp(`<p class="cap-text">${EARLY}</p>`))
  assert.deepEqual(shownCaption({ kind: 'line', text: LATER }, [EARLY]), { kind: 'line', text: EARLY })
  assert.equal(shownCaption(null, []), null)
  // A viewer's question and its answer are not tied to the clock: shown as given.
  assert.deepEqual(shownCaption({ kind: 'question', text: 'Who scores next?' }, [EARLY]), { kind: 'question', text: 'Who scores next?' })
})

test('the sidebar, the caption and the sport bar are never inside the video card; only the score bug and ON AIR are', () => {
  const html = render()
  const card = videoCard(html)
  for (const outside of ['class="side"', 'class="panel lines', 'aria-label="Proof"', 'aria-label="Shot map"', 'aria-label="Caption"', 'class="pickbar', 'aria-label="Sport"']) {
    assert.ok(!card.includes(outside), `${outside} sits outside the video card`)
    assert.ok(html.includes(outside), `${outside} is on the page`)
  }
  assert.match(card, /class="bug"><div class="scorebar glass"[\s\S]*class="onair glass on"/)
  assert.match(card, /class="controls"[\s\S]*aria-label="Pause"[\s\S]*aria-label="Seek"[\s\S]*aria-label="Mute commentary"[\s\S]*aria-label="Commentary volume"[\s\S]*aria-label="Fullscreen"/)
})

test('a question waits in the caption header without its prefix; the line on screen keeps the caption (#153)', () => {
  const html = render({ caption: { kind: 'question', text: 'A viewer asks: Who scores next?' } })
  assert.ok(!html.includes('A viewer asks:'), 'the Viewer chip says who asks')
  assert.match(html, /<span class="cap-side"><span class="chip viewer">Viewer<\/span><span class="cap-q">Who scores next\?<\/span><\/span><span class="cap-side cap-title">Kobe&#x27;s 81 v Toronto<\/span>/,
    'the match stays named beside the waiting question')
  assert.match(html, new RegExp(`<p class="cap-text">${EARLY}</p>`))
})

test('an answer shows under its question with the moment it was asked at, and the match is named', () => {
  const answered = { ...replay, answers: [{ line_id: 'a1', moment_idx: 3, question: 'Who scores next?', text: 'Kobe, on this form.' }] }
  const html = render({ replay: answered, caption: { kind: 'answer', text: 'Kobe, on this form.', speaker: 'analyst' } })
  assert.match(html, /<span class="chip analyst">Analyst<\/span><span class="tag">06:12 · [^<]+<\/span><span class="cap-side cap-title">Kobe&#x27;s 81 v Toronto<\/span><\/div><p class="cap-asks">A viewer asks: Who scores next\?<\/p><p class="cap-text">Kobe, on this form\.<\/p>/)
})

test('an off-air answer is a calm state with the Analyst chip, never a headline (#153)', () => {
  const answered = { ...replay, answers: [{ line_id: 'a1', moment_idx: 3, question: 'Who scores next?', text: 'The commentator is off air.', off_air: true }] }
  const html = render({ replay: answered, caption: { kind: 'answer', text: 'The commentator is off air.', speaker: 'analyst' } })
  assert.match(html, /<span class="chip analyst">Analyst<\/span>[\s\S]*<p class="cap-state">Couldn&#x27;t answer that one\. Try again\.<\/p>/)
  assert.ok(!html.includes('<p class="cap-text">The commentator'), 'no headline')
})

test('ON AIR names the speaker on air: the lead by the chosen voice, the analyst by the voice reading it (#153)', () => {
  assert.match(render(), /class="who">Lead · Sam</)
  const analyst = { ...replay, lines: [{ ...line(3, 490.5, EARLY), speaker: 'analyst' as const }] }
  const voice = { status: 'on', chip: 'Sam', speaking: true }
  assert.match(render({ replay: analyst, voice: { ...voice, analyst: 'George' } }), /class="who">Analyst · George</)
  assert.match(render({ replay: analyst, voice: { ...voice, chip: 'Browser voice', analyst: 'Browser voice' } }),
    /class="who">Analyst · Browser voice</, 'browser speech reads the analyst too')
  assert.match(render({ replay: analyst }), /class="who">Analyst</, 'no name rather than a wrong one')
})

test('a final settled on penalties says the shoot-out at full time', () => {
  const final: Match = { match_id: '3869685', sport: 'football', title: "Argentina v France, FIFA World Cup Final" }
  const last = { ...moment(68, 1600, '125:58'), sport: 'football' as const, type: 'Full time', score: { home: 3, away: 3 }, detail: { shootout: { home: 4, away: 2 } } }
  const html = render({ match: final, replay: { ...replay, moments: [last], lines: [], ended: true, now: 1670 }, onNext: noop })
  assert.match(html, /<p class="cap-text">Full time · ARG 3–3 FRA · pens 4–2<\/p>/)
})

test('at full time the picture offers Watch again and Next match; not before the picture gets there (#153)', () => {
  const over = { ...replay, ended: true, now: 1670 }
  const html = render({ replay: over, onNext: noop })
  assert.match(html, /class="overlay end" role="status"><span>Full time · LAK 64–69 RAP<\/span>[\s\S]*Watch again[\s\S]*Next match →/)
  assert.match(html, /<p class="cap-text">Full time · LAK 64–69 RAP<\/p>/, 'the caption says full time, not the last play')
  assert.match(html, /aria-label="Play"/, 'the transport offers play again, never pause')
  assert.ok(!render({ replay: { ...over, now: 1675, duration: 1671 } }).includes('27:55'), 'the clock stops at the duration')
  assert.ok(!render({ replay: { ...replay, ended: true } }).includes('Full time'), 'the stream ended but the picture is still at 500 s')
})

test('the Ask box wraps a long question so it reads from its start (#153)', () => {
  assert.match(render(), /<textarea id="ask-q" rows="1"/)
})

test('before the first call: a countdown to it, not "Waiting" (#153)', () => {
  const early = { ...replay, moments: [], lines: [], queuedMoments: [moment(5, 520, '04:10'), moment(3, 512, '06:12')] }
  assert.match(render({ replay: early }), /First call in 0:12/)
})

test('the Lines rows show the speaker and the time alone, the measure named in the title (#153)', () => {
  const html = render()
  assert.match(html, /<span class="chip lead">Lead<\/span><span class="num" title="model reply 0\.90 s">0\.90 s<\/span>/)
  assert.ok(!html.includes('>model reply'), 'the label is in the title only')
})

test('the bar sits in the nav row, and with no video the clock and scrubber go (#153)', () => {
  const html = render()
  assert.match(html, /<header class="nav">[\s\S]*class="pickbar glass"[\s\S]*<nav class="links"[\s\S]*>Matches<\/button>/)
  assert.match(render({ video: 'unavailable' }), /<section class="vcard"[^>]*data-video="off"/)
  assert.ok(!/<section class="vcard"[^>]*data-video/.test(html))
})

test('a replay the server turned away (#244) says why, and an Ask it turned away says why too', () => {
  const turned = { ...replay, phase: 'failed' as const, refused: 'Lots of people are watching. Try again in a minute.' }
  assert.match(render({ replay: turned }), /Lots of people are watching\. Try again in a minute\./)
  const notice = 'Commentator is off air for today'
  const answered = { ...replay, answers: [{ line_id: 'a1', moment_idx: 3, question: 'Who?', text: notice, off_air: true, notice }] }
  const html = render({ replay: answered, caption: { kind: 'answer', text: notice, speaker: 'analyst' } })
  assert.match(html, /<p class="cap-state">Commentator is off air for today<\/p>/)
})
