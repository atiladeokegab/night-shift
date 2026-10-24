// The only module that talks to the match server (docs/CONTRACT.md, 'HTTP'):
// GET /matches, GET /matches/{id}/start?at=, POST /replays {match_id, speed} -> {replay_id},
// GET /replays/{id}/stream (SSE: moment, line, stats per moment; error; end last),
// GET /stats, GET /voices, POST /lines/{id}/fix, POST /replays/{id}/ask, POST /replays/{id}/seen, GET /replays/{id}/players, .../players/{name}/shots and .../profile and GET /lines/{id}/audio?voice=<id>
// (ElevenLabs; 503 when the voice isn't configured).
import { demoMatches, demoStats, streamDemo } from './demo'
import { offAir } from './ask'
import { playersUrl, type Player, type Profile } from './follow'
import type { Shots } from './shots'
import type { Answer, Fix, Line, Match, Moment, ReviewItem, Stats, StreamEvent, Voice } from './types'

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

export async function getStats(): Promise<Stats> {
  if (isDemo) return demoStats()
  const res = await fetch('/stats')
  if (!res.ok) throw new Error(`GET /stats failed (${res.status})`)
  return res.json()
}

export async function createReplay(matchId: string, speed: number, startIdx?: number): Promise<string> {
  if (isDemo) return matchId
  const res = await fetch('/replays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ match_id: matchId, speed, start_idx: startIdx }),
  })
  if (!res.ok) throw new Error(`POST /replays failed (${res.status})`)
  return ((await res.json()) as { replay_id: string }).replay_id
}

// The video's start for a replay that jumps to moment `at` (#188); null without a video.
export async function videoStartAt(matchId: string, at: number): Promise<number | null> {
  if (isDemo) return null
  const res = await fetch(`/matches/${encodeURIComponent(matchId)}/start?at=${at}`)
  return res.ok ? ((await res.json()) as { video_start: number | null }).video_start : null
}

// Follows a replay's stream from the start; a late or reconnected subscriber gets every event again,
// so the caller drops moments and lines it already has. Returns a function that stops listening.
// The page's heartbeat once a replay's stream has ended, well under the server's FORGET_S (60 s), so a
// paused viewer can still ask about the moment on screen (#156). It stops when the page leaves the replay.
const SEEN_MS = 20_000

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
  source.addEventListener('moment', (e) => onEvent({ type: 'moment', moment: JSON.parse(e.data) as Moment }))
  source.addEventListener('line', (e) => onEvent({ type: 'line', line: JSON.parse(e.data) as Line }))
  source.addEventListener('stats', (e) => onEvent({ type: 'stats', stats: JSON.parse(e.data) as Stats }))
  source.addEventListener('fixed', (e) => onEvent({ type: 'fixed', fix: JSON.parse(e.data) as Fix }))
  source.addEventListener('answer', (e) => onEvent({ type: 'answer', answer: JSON.parse(e.data) as Answer }))
  source.addEventListener('error', (e) => {
    // A server `error` event carries {detail}; a dropped connection is a plain Event with no data.
    const data = (e as MessageEvent).data
    if (data) {
      console.error('commentator error', data)
      return onEvent({ type: 'error', detail: (JSON.parse(data) as { detail: string }).detail })
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
export class FixError extends Error {
  status: number
  constructor(status: number) {
    super(`POST /lines/{id}/fix failed (${status})`)
    this.status = status
  }
}

// GET /review (#171): stored lines the number check flags. The demo has no store, so nothing.
export async function getReview(): Promise<ReviewItem[]> {
  if (isDemo) return []
  const res = await fetch('/review')
  if (!res.ok) throw new Error(`GET /review failed (${res.status})`)
  return res.json()
}

export async function postFix(lineId: string, correctedText: string, reason: string): Promise<Fix> {
  if (isDemo) throw new FixError(503) // the demo has no server to keep a fix
  const res = await fetch(`/lines/${encodeURIComponent(lineId)}/fix`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ corrected_text: correctedText, reason }),
  })
  if (!res.ok) throw new FixError(res.status)
  return res.json()
}

// POST /replays/{id}/ask, about the match up to the moment on screen. Off air (the server's own off-air
// answer, or any failure here) is the calm copy, never an error.
export async function askCommentator(replayId: string, question: string, momentIdx: number): Promise<Answer> {
  if (isDemo) return offAir(question, momentIdx) // the demo has no commentator to ask
  try {
    const res = await fetch(`/replays/${encodeURIComponent(replayId)}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, moment_idx: momentIdx }),
    })
    if (res.ok) return res.json()
  } catch {
    // the network failed: off air below
  }
  return offAir(question, momentIdx)
}

// GET /replays/{id}/players/{name}/shots (#120), up to the moment on screen. null: no shot record for
// this player or match (a 404), and in the demo, which has no server.
export async function getShots(replayId: string, name: string, momentIdx: number): Promise<Shots | null> {
  if (isDemo) return null
  const res = await fetch(`/replays/${encodeURIComponent(replayId)}/players/${encodeURIComponent(name)}/shots?moment_idx=${momentIdx}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`GET shots failed (${res.status})`)
  return res.json()
}

// GET /replays/{id}/players (#140): everyone in the match so far; empty in the demo, which has no server.
export async function getPlayers(replayId: string, at: number): Promise<Player[]> {
  if (isDemo) return []
  const res = await fetch(playersUrl(replayId, at))
  if (res.status === 404) return []
  if (!res.ok) throw new Error(`GET players failed (${res.status})`)
  return res.json()
}

// GET /replays/{id}/players/{name}/profile (#140), up to the moment on screen. null: no such player.
export async function getProfile(replayId: string, name: string, momentIdx: number): Promise<Profile | null> {
  if (isDemo) return null
  const res = await fetch(`/replays/${encodeURIComponent(replayId)}/players/${encodeURIComponent(name)}/profile?moment_idx=${momentIdx}`)
  if (res.status === 404) return null
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
