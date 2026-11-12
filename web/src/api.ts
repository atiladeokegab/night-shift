// The only module that talks to the match server (docs/CONTRACT.md, 'HTTP'):
// GET /matches, GET /matches/{id}/start[?at=] (and its marks), POST /replays {match_id, speed} -> {replay_id},
// GET /replays/{id}/stream (SSE: moment, line, stats per moment; error; end last),
// GET /stats, GET /voices, POST /lines/{id}/fix, GET /lines/{id}, POST /replays/{id}/ask, POST /replays/{id}/seen, POST /replays/{id}/look, GET /replays/{id}/players, .../players/{name}/shots and .../profile and GET /lines/{id}/audio?voice=<id>
// (ElevenLabs; 503 when the voice isn't configured).
import { demoMatches, demoStats, streamDemo } from './demo'
import { offAir, Refused, refused } from './ask'
import { replayGone } from './ended'
import { playersUrl, type Player, type Profile } from './follow'
import type { Shots } from './shots'
import type { Answer, Fix, Line, LineCheck, Ledger, LineCheckExample, Match, Moment, ReviewItem, ScoreCheckExample, ScoreCheckReceipt, Stats, TrainingState, StreamEvent, Teams, Voice } from './types'

export const isDemo = new URLSearchParams(window.location.search).has('demo')

export type StreamStatus = 'ok' | 'reconnecting' | 'disconnected'

// The design's 'Disconnected after 3 tries'.
const MAX_TRIES = 3

export async function listMatches(): Promise<Match[]> {
  if (isDemo) return demoMatches
  const res = await fetch('/matches')
  if (!res.ok) throw new Error(`GET /matches failed (${res.status})`)
  return res.json()
}

export async function getStats(signal?: AbortSignal): Promise<Stats> {
  if (isDemo) return demoStats()
  const res = await fetch('/stats', { signal })
  if (!res.ok) throw new Error(`GET /stats failed (${res.status})`)
  return res.json()
}

export async function getTeams(sport: string, matchId: string): Promise<Teams> {
  if (isDemo) return { teams: [], head_to_head: [] }
  const res = await fetch(`/teams/${encodeURIComponent(sport)}/${encodeURIComponent(matchId)}`)
  if (!res.ok) throw new Error(`GET /teams failed (${res.status})`)
  return res.json()
}

export async function createReplay(matchId: string, speed: number, startIdx?: number): Promise<string> {
  if (isDemo) return matchId
  const res = await fetch('/replays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ match_id: matchId, speed, start_idx: startIdx }),
  })
  if (!res.ok) {
    const busy = await refused(res)
    throw busy ? new Refused(busy) : new Error(`POST /replays failed (${res.status})`)
  }
  return ((await res.json()) as { replay_id: string }).replay_id
}

// The video's start for a replay that jumps to moment `at` (#188); null without a video.
export async function videoStartAt(matchId: string, at: number): Promise<number | null> {
  if (isDemo) return null
  const res = await fetch(`/matches/${encodeURIComponent(matchId)}/start?at=${at}`).catch(() => null)
  return res?.ok ? ((await res.json().catch(() => ({ video_start: null }))) as { video_start: number | null }).video_start : null
}

// Every mapped moment's video time, so the timeline marks them all at load; null without a server answer.
export async function videoMarks(matchId: string): Promise<Match['marks'] | null> {
  if (isDemo) return null
  const res = await fetch(`/matches/${encodeURIComponent(matchId)}/start`).catch(() => null)
  return res?.ok ? ((await res.json()) as { marks: Match['marks'] }).marks : null
}

// Follows a replay's stream from the start; a late or reconnected subscriber gets every event again,
// so the caller drops moments and lines it already has. Returns a function that stops listening.
// The page's heartbeat once a replay's stream has ended, well under the server's FORGET_S (60 s), so a
// paused viewer can still ask about the moment on screen (#156). It stops when the page leaves the replay.
const SEEN_MS = 20_000

function parsed<T>(data: string): T | undefined {
  try {
    return JSON.parse(data) as T
  } catch {
    console.error('malformed stream event', data)
    return undefined
  }
}

export function followReplay(
  replayId: string,
  onEvent: (e: StreamEvent) => void,
  onStatus: (s: StreamStatus) => void,
): () => void {
  if (isDemo) return streamDemo(replayId, onEvent)

  const source = new EventSource(`/replays/${encodeURIComponent(replayId)}/stream`)
  let tries = 0
  source.addEventListener('open', () => {
    if (tries > 0) onStatus('ok')
    tries = 0
  })
  // A malformed event is dropped, never thrown: the stream and the events after it carry on.
  const on = <T>(type: string, emit: (data: T) => void) => source.addEventListener(type, (e) => {
    const data = parsed<T>((e as MessageEvent).data)
    if (data !== undefined) emit(data)
  })
  on<Moment>('moment', (moment) => onEvent({ type: 'moment', moment }))
  on<Line>('line', (line) => onEvent({ type: 'line', line }))
  on<Stats>('stats', (stats) => onEvent({ type: 'stats', stats }))
  on<Fix>('fixed', (fix) => onEvent({ type: 'fixed', fix }))
  on<LineCheck>('linecheck', (check) => onEvent({ type: 'linecheck', check }))
  on<Answer>('answer', (answer) => onEvent({ type: 'answer', answer }))
  source.addEventListener('error', (e) => {
    // A server `error` event carries {detail}; a dropped connection is a plain Event with no data.
    const data = (e as MessageEvent).data
    if (data) {
      console.error('commentator error', data)
      return onEvent({ type: 'error', detail: parsed<{ detail?: string }>(data)?.detail ?? String(data) })
    }
    tries += 1
    if (tries >= MAX_TRIES || source.readyState === EventSource.CLOSED) {
      source.close()
      onStatus('disconnected')
    } else {
      onStatus('reconnecting')
    }
  })
  let beat: number | undefined
  source.addEventListener('end', () => {
    // Close before the server does, or EventSource reconnects and replays the whole match again.
    source.close()
    const seen = () => fetch(`/replays/${encodeURIComponent(replayId)}/seen`, { method: 'POST' }).catch(() => {})
    beat = window.setInterval(seen, SEEN_MS)
    onEvent({ type: 'end' })
  })
  return () => {
    source.close()
    window.clearInterval(beat)
  }
}

// POST /lines/{id}/fix. A 503 means the Mubit call failed and nothing was stored, so it can be sent again.
// A 422 with `wrong` means the number check refused the fix (#232): nothing stored, edit and send again.
export class FixError extends Error {
  status: number
  wrong: string[]
  constructor(status: number, wrong: string[] = []) {
    super(`POST /lines/{id}/fix failed (${status})`)
    this.status = status
    this.wrong = wrong
  }
}

// GET /lines/{id} → the Line check example a fix sent (#305). Core sends it after answering the fix, so
// it is asked for every 2 s for up to a minute; only one made since the fix counts. Null if none comes.
export async function waitForExample(fix: Fix, tries = 30, every = 2000): Promise<LineCheckExample | null> {
  if (isDemo) return null
  const since = typeof fix.created_at === 'string' ? fix.created_at : ''
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, every))
    const res = await fetch(`/lines/${encodeURIComponent(fix.line_id)}`).catch(() => null)
    const ex: LineCheckExample | undefined = res?.ok ? (await res.json()).linecheck_example : undefined
    if (ex && ex.created_at >= since) return ex
  }
  return null
}

// A signal that aborts after `ms`, or with `outer`: no read waits on a stalled request.
export function timed(outer: AbortSignal | undefined, ms: number): AbortSignal {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), ms)
  const stop = () => (clearTimeout(t), ctl.abort())
  if (outer?.aborted) stop()
  else outer?.addEventListener('abort', stop, { once: true })
  return ctl.signal
}

const READ_MS = 5_000 // one GET /lines/{id}, its body included
const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000] // then 8 s each

// GET /lines/{id} → this fix's own Score check examples and its receipt (#400), matched by `fix_uid`, never
// by time. `seen` gets each change. It stops at the receipt, after `deadline` ms, or when `signal` aborts
// (the panel closed); no receipt by then is 'unknown', never "none sent".
export async function followTraining(fix: Fix, seen: (state: TrainingState, xs: ScoreCheckExample[]) => void,
  signal: AbortSignal, deadline = 60_000): Promise<TrainingState> {
  if (isDemo || !fix.fix_uid) return 'unknown'
  const end = Date.now() + deadline
  let n = 0
  for (let i = 0; !signal.aborted && Date.now() < end; i++) {
    await new Promise<void>((r) => timed(signal, Math.min(BACKOFF_MS[Math.min(i, 3)], end - Date.now())).addEventListener('abort', () => r()))
    if (signal.aborted) break
    const s = timed(signal, READ_MS)
    const line = await fetch(`/lines/${encodeURIComponent(fix.line_id)}`, { signal: s })
      .then((res) => (res.ok ? res.json() : null))
      .catch(() => null)
    const xs: ScoreCheckExample[] = (line?.scorecheck_examples ?? []).filter((x: ScoreCheckExample) => x.fix_uid === fix.fix_uid)
    const got: ScoreCheckReceipt | undefined = (line?.scorecheck_receipts ?? []).find((r: ScoreCheckReceipt) => r.fix_uid === fix.fix_uid)
    if (got) {
      const state = got.sent > 0 ? 'sent' : got.failed ? 'failed' : got.held_out ? 'held_out' : 'none'
      seen(state, xs)
      return state
    }
    if (xs.length > n) seen('pending', xs)
    n = Math.max(n, xs.length)
  }
  return 'unknown'
}

// GET /review (#171): stored lines the number check flags. The demo has no store, so nothing.
export async function getReview(): Promise<ReviewItem[]> {
  if (isDemo) return []
  const res = await fetch('/review')
  if (!res.ok) throw new Error(`GET /review failed (${res.status})`)
  return res.json()
}

// GET /ledger: every correction sent to Mubit. The demo has no store, so none.
export async function getLedger(): Promise<Ledger> {
  if (isDemo) return { sent: 0, rows: [] }
  const res = await fetch('/ledger')
  if (!res.ok) throw new Error(`GET /ledger failed (${res.status})`)
  return res.json()
}

// The producer token (#232): asked once, on the first 401, and kept in this browser.
const TOKEN = 'producer-token'
let sessionToken = ''
export function setProducerToken(token: string): void {
  try {
    localStorage.setItem(TOKEN, token)
  } catch {
    // storage blocked: the fix is still sent with it below this once
  }
  sessionToken = token
}
function producerToken(): string {
  try {
    return localStorage.getItem(TOKEN) ?? sessionToken
  } catch {
    return sessionToken
  }
}

export async function postFix(lineId: string, correctedText: string, reason: string): Promise<Fix> {
  if (isDemo) throw new FixError(503) // the demo has no server to keep a fix
  const res = await fetch(`/lines/${encodeURIComponent(lineId)}/fix`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Producer-Token': producerToken() },
    body: JSON.stringify({ corrected_text: correctedText, reason }),
  })
  if (!res.ok) {
    const detail = res.status === 422 ? (await res.json().catch(() => null))?.detail : null
    throw new FixError(res.status, Array.isArray(detail?.wrong) ? detail.wrong : [])
  }
  return res.json()
}

// POST /replays/{id}/ask, about the match up to the moment on screen. Off air (the server's own off-air
// answer, or any failure here) is the calm copy, never an error.
// null: the server has dropped the replay (#454), which useReplay hears from ended.ts.
export async function askCommentator(replayId: string, question: string, momentIdx: number): Promise<Answer | null> {
  if (isDemo) return offAir(question, momentIdx) // the demo has no commentator to ask
  try {
    const res = await fetch(`/replays/${encodeURIComponent(replayId)}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, moment_idx: momentIdx }),
    })
    if (res.ok) return res.json()
    if (await replayGone(res, replayId)) return null
    const busy = await refused(res)
    if (busy) return { ...offAir(question, momentIdx), text: busy, notice: busy }
  } catch {
    // the network failed: off air below
  }
  return offAir(question, momentIdx)
}

// POST /replays/{id}/look (#291): one frame of the shared tab, base64 JPEG, and the video time. false: send
// no more (the replay is over or has had every frame it takes, a 404 or 410); a 429 or a failure is one frame
// skipped. The demo has no commentators to watch.
export async function lookAt(replayId: string, image: string, t: number): Promise<boolean> {
  if (isDemo) return false
  try {
    const res = await fetch(`/replays/${encodeURIComponent(replayId)}/look`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image, t }),
    })
    await replayGone(res, replayId)
    return res.status !== 404 && res.status !== 410
  } catch {
    return true
  }
}

// GET /replays/{id}/players/{name}/shots (#120), up to the moment on screen. null: no shot record for
// this player or match (a 404), and in the demo, which has no server.
export async function getShots(replayId: string, name: string, momentIdx: number): Promise<Shots | null> {
  if (isDemo) return null
  const res = await fetch(`/replays/${encodeURIComponent(replayId)}/players/${encodeURIComponent(name)}/shots?moment_idx=${momentIdx}`)
  if (await replayGone(res, replayId) || res.status === 404) return null
  if (!res.ok) throw new Error(`GET shots failed (${res.status})`)
  return res.json()
}

// GET /replays/{id}/players (#140): everyone in the match so far; empty in the demo, which has no server.
export async function getPlayers(replayId: string, at: number): Promise<Player[]> {
  if (isDemo) return []
  const res = await fetch(playersUrl(replayId, at))
  if (await replayGone(res, replayId) || res.status === 404) return []
  if (!res.ok) throw new Error(`GET players failed (${res.status})`)
  return res.json()
}

// GET /replays/{id}/players/{name}/profile (#140), up to the moment on screen. null: no such player.
export async function getProfile(replayId: string, name: string, momentIdx: number): Promise<Profile | null> {
  if (isDemo) return null
  const res = await fetch(`/replays/${encodeURIComponent(replayId)}/players/${encodeURIComponent(name)}/profile?moment_idx=${momentIdx}`)
  if (await replayGone(res, replayId) || res.status === 404) return null
  if (!res.ok) throw new Error(`GET profile failed (${res.status})`)
  return res.json()
}

export function lineAudioUrl(lineId: string, voiceId?: string): string {
  const url = `/lines/${encodeURIComponent(lineId)}/audio`
  return voiceId ? `${url}?voice=${encodeURIComponent(voiceId)}` : url
}

// The page's own speechSynthesis voices, offered when the server lists none (no /voices yet, or 503):
// the PRD's defaults, an Indian voice for cricket and a British one for football.
export const BROWSER_VOICES: Voice[] = [
  { id: 'browser-en-GB', label: 'British (browser)', lang: 'en-GB', default_for: 'football', browser: true },
  { id: 'browser-en-IN', label: 'Indian (browser)', lang: 'en-IN', default_for: 'cricket', browser: true },
]

export async function listVoices(): Promise<Voice[]> {
  if (isDemo) return BROWSER_VOICES
  try {
    const res = await fetch('/voices')
    const voices = res.ok ? ((await res.json()) as Voice[]) : []
    return voices.length ? voices : BROWSER_VOICES
  } catch {
    return BROWSER_VOICES
  }
}
