// The only module that talks to the match server (docs/CONTRACT.md, "HTTP"):
// GET /matches, POST /replays {match_id, speed} -> {replay_id},
// GET /replays/{id}/stream (SSE: moment, line, stats per moment; error; end last),
// GET /lines/{id}/audio (the line read by ElevenLabs, 503 when the voice isn't configured).
import { demoMatches, streamDemo } from './demo'
import type { Line, Match, Moment, StreamEvent } from './types'

export const isDemo = new URLSearchParams(window.location.search).has('demo')

export type StreamStatus = 'ok' | 'reconnecting' | 'disconnected'

// The design's "Disconnected after 3 tries".
const MAX_TRIES = 3

export async function listMatches(): Promise<Match[]> {
  if (isDemo) return demoMatches
  const res = await fetch('/matches')
  if (!res.ok) throw new Error(`GET /matches failed (${res.status})`)
  return res.json()
}

export async function createReplay(matchId: string, speed: number): Promise<string> {
  if (isDemo) return matchId
  const res = await fetch('/replays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ match_id: matchId, speed }),
  })
  if (!res.ok) throw new Error(`POST /replays failed (${res.status})`)
  return ((await res.json()) as { replay_id: string }).replay_id
}

// Follows a replay's stream from the start; a late or reconnected subscriber gets every event again,
// so the caller drops moments and lines it already has. Returns a function that stops listening.
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
  source.addEventListener('error', (e) => {
    // A server `error` event carries {detail}; a dropped connection is a plain Event with no data.
    const data = (e as MessageEvent).data
    if (data) return onEvent({ type: 'error', detail: (JSON.parse(data) as { detail: string }).detail })
    tries += 1
    if (tries >= MAX_TRIES || source.readyState === EventSource.CLOSED) {
      source.close()
      onStatus('disconnected')
    } else {
      onStatus('reconnecting')
    }
  })
  source.addEventListener('end', () => {
    // Close before the server does, or EventSource reconnects and replays the whole match again.
    source.close()
    onEvent({ type: 'end' })
  })
  return () => source.close()
}

export function lineAudioUrl(lineId: string): string {
  return `/lines/${encodeURIComponent(lineId)}/audio`
}
