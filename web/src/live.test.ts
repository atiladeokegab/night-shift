import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { registerHooks } from 'node:module'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { transformSync } from 'rolldown/experimental'
import { eyesKey } from './eyes.ts'
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

test('an answer shows under its question with the time it was asked at, and the match is named', () => {
  const answered = { ...replay, answers: [{ line_id: 'a1', moment_idx: 3, question: 'Who scores next?', text: 'Kobe, on this form.' }] }
  const html = render({ replay: answered, caption: { kind: 'answer', text: 'Kobe, on this form.', speaker: 'analyst' } })
  assert.match(html, /<span class="chip analyst">Analyst<\/span><span class="tag">at 06:12<\/span><span class="cap-side cap-title">Kobe&#x27;s 81 v Toronto<\/span><\/div><p class="cap-asks">A viewer asks: Who scores next\?<\/p><p class="cap-text">Kobe, on this form\.<\/p>/)
})

test('an off-air answer is a calm state with the Analyst chip, never a headline (#153)', () => {
  const answered = { ...replay, answers: [{ line_id: 'a1', moment_idx: 3, question: 'Who scores next?', text: 'The commentator is off air.', off_air: true }] }
  const html = render({ replay: answered, caption: { kind: 'answer', text: 'The commentator is off air.', speaker: 'analyst' } })
  assert.match(html, /<span class="chip analyst">Analyst<\/span>[\s\S]*<p class="cap-state">Couldn&#x27;t answer that one\. Try again\.<\/p>/)
  assert.ok(!html.includes('<p class="cap-text">The commentator'), 'no headline')
})

test('ON AIR names the speaker on air: the lead by the chosen voice, the analyst by the voice reading it (#153)', () => {
  assert.match(render(), /class="who" aria-hidden="true">Lead · Sam</)
  const analyst = { ...replay, lines: [{ ...line(3, 490.5, EARLY), speaker: 'analyst' as const }] }
  const voice = { status: 'on', chip: 'Sam', speaking: true }
  assert.match(render({ replay: analyst, voice: { ...voice, analyst: 'George' } }), /class="who" aria-hidden="true">Analyst · George</)
  assert.match(render({ replay: analyst, voice: { ...voice, chip: 'Browser voice', analyst: 'Browser voice' } }),
    /class="who" aria-hidden="true">Analyst · Browser voice</, 'browser speech reads the analyst too')
  assert.match(render({ replay: analyst }), /class="who" aria-hidden="true">Analyst</, 'no name rather than a wrong one')
})

test('the ON AIR pill announces OFF AIR and VOICE OFF/UNAVAILABLE, never a speaker change while the voice is on', () => {
  // What a screen reader hears from the status: its text minus anything aria-hidden.
  const heard = (html: string) => html.match(/<span class="st" role="status">([\s\S]*?)<\/span><\/(?:span|button)>/)?.[1]
    ?.replace(/<span[^>]*aria-hidden="true"[^>]*>[\s\S]*?<\/span>(?:<\/span>)*/g, '').replace(/<[^>]+>/g, '')
  const analyst = { ...replay, lines: [{ ...line(3, 490.5, EARLY), speaker: 'analyst' as const }] }
  const lead = heard(render())
  assert.equal(lead, 'ON AIR')
  assert.equal(heard(render({ replay: analyst, voice: { status: 'on', chip: 'Sam', speaking: true, analyst: 'George' } })), lead)
  assert.equal(heard(render({ voice: { status: 'off', chip: 'Sam', speaking: false } })), 'VOICE OFFSubtitles only')
  assert.equal(heard(render({ voice: { status: 'unavailable', chip: 'Sam', speaking: false } })), 'VOICE UNAVAILABLESubtitles carry on')
  assert.match(heard(render({ replay: { ...replay, error: 'gone' } })) ?? '', /^OFF AIR/)
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

test("an answer shows its own time, and dims on the caption and in the log once a later moment is on screen", () => {
  const asked = { line_id: 'a1', moment_idx: 3, question: 'Where are we?', text: 'Sixty-three to sixty-nine, Raptors lead.' }
  const caption = { kind: 'answer' as const, text: asked.text, speaker: 'analyst' as const }
  const fresh = render({ replay: { ...replay, answers: [asked] }, caption })
  assert.match(fresh, /at 06:12/)
  assert.doesNotMatch(fresh, /stale/)
  const later = render({ replay: { ...replay, now: 510, answers: [asked] }, caption }) // 05:40 is on screen now
  assert.match(later, /class="caption glass stale"/)
  assert.match(later, /class="qa stale"/)
  assert.match(later, /Where are we\?<span class="at nw"> · at 06:12<\/span>/)
})

test('Close your eyes covers the picture and leaves the player playing under it (#277)', () => {
  const open = videoCard(render())
  const shut = videoCard(render({ closed: true }))
  // The cover only adds itself: the player's markup is the same (never paused, hidden or unmounted),
  // and the play button still offers Pause.
  const player = (html: string) => html.slice(html.indexOf('<div id="video"'), html.indexOf('<div class="bug"'))
  assert.equal(player(shut).replace(/<div class="eyes"[\s\S]*?<\/div>/, ''), player(open))
  assert.match(shut, /aria-label="Pause"/)
  assert.match(shut, /aria-pressed="true"[^>]*>[\s\S]*?Close your eyes/)
  assert.match(open, /aria-pressed="false"[^>]*>[\s\S]*?Close your eyes/)
  // The cover shows the line on screen and keeps the score; the shown line, never a later one (A-6.4).
  assert.match(shut, new RegExp(`<div class="eyes" aria-hidden="true"><p>${EARLY}</p></div>`))
  assert.ok(!shut.includes(LATER))
  assert.match(shut, /class="bug"><div class="scorebar glass"/)
})

test('with no video, Close your eyes still covers the page to its line and score (#338)', () => {
  // a video that can't play here (a venue blocking YouTube) and a whole match with no video at all
  for (const props of [{ video: 'unavailable' }, { match: { ...match, youtube_id: undefined } }]) {
    const open = videoCard(render(props))
    const shut = videoCard(render({ ...props, closed: true }))
    assert.match(open, /aria-pressed="false"[^>]*aria-keyshortcuts="E"[^>]*>[\s\S]*?Close your eyes/)
    assert.ok(!open.includes('class="eyes"'))
    assert.match(shut, /aria-pressed="true"[^>]*>[\s\S]*?Close your eyes/)
    assert.match(shut, new RegExp(`<div class="eyes" aria-hidden="true"><p>${EARLY}</p></div>`))
    assert.match(shut, /class="bug"><div class="scorebar glass"/)
  }
})

test('E toggles the cover, but not typed into Ask or with a modifier (#277)', () => {
  const key = (k: string, target: unknown = null, mods = {}) =>
    eyesKey({ key: k, repeat: false, ctrlKey: false, metaKey: false, altKey: false, target: target as EventTarget, ...mods })
  const field = { closest: (sel: string) => (sel.includes('input') ? {} : null) }
  const page = { closest: () => null }
  assert.equal(key('e', page), true)
  assert.equal(key('E', page), true)
  assert.equal(key('e', field), false)
  assert.equal(key('e', page, { ctrlKey: true }), false)
  assert.equal(key('w', page), false)
})

test('a whole match with no video says what it is, never that highlights can\'t play (#284)', () => {
  const whole = { ...match, match_id: '7457', sport: 'football' as const, youtube_id: undefined, video_start: undefined }
  const html = videoCard(render({ match: whole, video: 'unavailable' }))
  assert.match(html, /<p class="novideo">Whole match, every key moment · described from the match data<\/p>/)
  assert.ok(!html.includes("Highlights can't play here"))
  assert.match(html, /aria-label="[^"]* match"/)
})

test('a video that should play but can\'t keeps saying so, and the commentary carries on (#284)', () => {
  const html = videoCard(render({ video: 'unavailable' }))
  assert.match(html, /<p class="novideo">Highlights can&#x27;t play here\. Commentary carries on, timed to the replay\.<\/p>/)
  assert.ok(!html.includes('described from the match data'))
})

// Let them watch (#291): the browser's screen sharing, faked; node has none of its own.
const share = { getDisplayMedia: async () => new MediaStream() } as unknown as MediaDevices
function withSharing<T>(media: MediaDevices | undefined, fn: () => T): T {
  Object.defineProperty(globalThis.navigator, 'mediaDevices', { value: media, configurable: true })
  try {
    return fn()
  } finally {
    Object.defineProperty(globalThis.navigator, 'mediaDevices', { value: undefined, configurable: true })
  }
}

test('Let them watch is in the controls of a video match, where the browser can share a tab (#291)', () => {
  const onLook = async () => true
  const card = withSharing(share, () => videoCard(render({ onLook })))
  assert.match(card, /class="controls"[\s\S]*<button class="ctl eyes-btn watch-btn" aria-label="Let them watch"[^>]*>[\s\S]*Let them watch<\/span><\/button>[\s\S]*Close your eyes/)
  assert.ok(!card.includes("They're watching"), 'no chip before the tab is shared')
  // no screen sharing, a match with no video, or no server (onLook unset): no button
  const whole = { ...match, youtube_id: undefined, video_start: undefined }
  assert.ok(!withSharing(undefined, () => render({ onLook })).includes('Let them watch'))
  assert.ok(!withSharing(share, () => render({ onLook, match: whole, video: 'unavailable' })).includes('Let them watch'))
  assert.ok(!withSharing(share, () => render()).includes('Let them watch'))
})

test('while they watch, a chip says so with a Stop button, and a screen reader hears it (#291)', async () => {
  const { Watching } = await import('./components/Watch.tsx')
  const on = renderToStaticMarkup(createElement(Watching, { on: true, onStart: noop, onStop: noop }))
  assert.match(on, /<span class="sr-only" role="status">They&#x27;re watching the screen<\/span>/)
  assert.match(on, /<span class="chip"><b aria-hidden="true"><\/b>They&#x27;re watching<\/span><button class="ctl eyes-btn" aria-label="Stop: they stop watching"><span>Stop<\/span><\/button>/)
  const asking = renderToStaticMarkup(createElement(Watching, { on: false, asking: true, onStart: noop, onStop: noop }))
  assert.match(asking, /<span class="sr-only" role="status"><\/span><button class="ctl eyes-btn watch-btn" disabled=""/)
})

test('a line whose retry passed the number check is tagged Auto-fixed, with its reason for a screen reader (#338)', () => {
  const html = render({ replay: { ...replay, now: 510, lines: [{ ...line(4, 508, LATER), retried: true }, line(3, 490.5, EARLY)] } })
  const log = html.slice(html.indexOf('<ul class="log">'))
  const li = (text: string) => log.slice(log.lastIndexOf('<li', log.indexOf(text)), log.indexOf('</li>', log.indexOf(text)))
  assert.match(li(LATER), /<span class="pill fixed auto" title="[^"]+">Auto-fixed<span class="sr-only">: its first try failed the number check, and the retry passed<\/span><\/span>/)
  assert.ok(!li(EARLY).includes('Auto-fixed'))
})
