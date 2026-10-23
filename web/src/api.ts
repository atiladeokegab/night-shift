// The only module that talks to the match server (docs/CONTRACT.md, "HTTP"):
// GET /matches, POST /replays {match_id, speed} -> {replay_id},
// GET /replays/{id}/stream (SSE: moment, line, stats per moment; error; end last).
import { demoMatches, streamDemo } from './demo'
import type { Line, Match, Moment, StreamEvent } from './types'

export const isDemo = new URLSearchParams(window.location.search).has('demo')

export async function listMatches(): Promise<Match[]> {
  if (isDemo) return demoMatches
  const res = await fetch('/matches')
  if (!res.ok) throw new Error(await failure('GET /matches', res))
  return res.json()
}

// Starts a replay and streams its events; returns a function that stops listening.
export async function startReplay(
  matchId: string,
  speed: number,
  onEvent: (e: StreamEvent) => void,
): Promise<() => void> {
  if (isDemo) return streamDemo(matchId, onEvent)

  const res = await fetch('/replays', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ match_id: matchId, speed }),
  })
  if (!res.ok) throw new Error(await failure('POST /replays', res))
  const { replay_id } = (await res.json()) as { replay_id: string }

  const source = new EventSource(`/replays/${encodeURIComponent(replay_id)}/stream`)
  source.addEventListener('moment', (e) => onEvent({ type: 'moment', moment: JSON.parse(e.data) as Moment }))
  source.addEventListener('line', (e) => onEvent({ type: 'line', line: JSON.parse(e.data) as Line }))
  source.addEventListener('error', (e) => {
    // A server `error` event carries {detail}; a dropped connection is a plain Event with no data.
    const data = (e as MessageEvent).data
    if (data) onEvent({ type: 'error', detail: (JSON.parse(data) as { detail: string }).detail })
    else if (source.readyState === EventSource.CLOSED) onEvent({ type: 'error', detail: 'Lost the match stream.' })
  })
  source.addEventListener('end', () => {
    // Close before the server does, or EventSource reconnects and replays the whole match again.
    source.close()
    onEvent({ type: 'end' })
  })
  return () => source.close()
}

async function failure(what: string, res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: string } | null
  if (res.status === 503) return 'The commentator is not configured on the server.'
  return `${what} failed (${res.status})${body?.detail ? `: ${body.detail}` : ''}`
}
