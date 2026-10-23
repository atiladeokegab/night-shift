// The only module that talks to the match server. Endpoints from issue #18:
// GET /matches, POST /replays {match_id, speed}, GET /replays/{id}/stream (SSE: moment, line, stats).
import { demoMatches, streamDemo } from './demo'
import type { Line, Match, Moment, StreamEvent } from './types'

export const isDemo = new URLSearchParams(window.location.search).has('demo')

export async function listMatches(): Promise<Match[]> {
  if (isDemo) return demoMatches
  const res = await fetch('/matches')
  if (!res.ok) throw new Error(`GET /matches failed: ${res.status}`)
  return res.json()
}

// Starts a replay and streams its events; returns a function that stops listening.
export async function startReplay(
  matchId: string,
  speed: number,
  onEvent: (e: StreamEvent) => void,
  onError: (message: string) => void,
): Promise<() => void> {
  if (isDemo) return streamDemo(matchId, onEvent)

  const res = await fetch('/replays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ match_id: matchId, speed }),
  })
  if (!res.ok) throw new Error(`POST /replays failed: ${res.status}`)
  const { id } = (await res.json()) as { id: string }

  const source = new EventSource(`/replays/${encodeURIComponent(id)}/stream`)
  source.addEventListener('moment', (e) => onEvent({ type: 'moment', moment: JSON.parse(e.data) as Moment }))
  source.addEventListener('line', (e) => onEvent({ type: 'line', line: JSON.parse(e.data) as Line }))
  source.addEventListener('end', () => {
    onEvent({ type: 'end' })
    source.close()
  })
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) onError('Lost the match stream.')
  }
  return () => source.close()
}
