// Demo feed for building the page without the match server: only used with ?demo, never as a fallback.
// Moments follow the contract's shapes; the lines are docs/design.md's samples, not commentator output.
import type { Line, Match, Moment, Stats, StreamEvent } from './types'

export const demoMatches: Match[] = [
  { match_id: '3906390', sport: 'football', title: "Spain Women's v England Women's, Women's World Cup Final", sample: true },
  { match_id: '1298150', sport: 'cricket', title: 'India v Pakistan, ICC Men\'s T20 World Cup match 16', sample: true },
]

const football = (idx: number, m: Partial<Moment>): Moment => ({
  sport: 'football', match_id: '3906390', idx, period: 1, clock: '00:00', type: 'Shot', team: "Spain Women's",
  players: {}, outcome: '', score: { home: 0, away: 0 }, detail: {}, ...m,
})
const cricket = (idx: number, m: Partial<Moment>): Moment => ({
  sport: 'cricket', match_id: '1298150', idx, period: 2, clock: '0.0', type: 'Six', team: 'India',
  players: {}, outcome: '', score: { runs: 0, wickets: 0, target: 160 }, detail: {}, ...m,
})

const feeds: Record<string, [Moment, string][]> = {
  '3906390': [
    [football(0, { clock: '15:11', team: "England Women's", players: { shooter: 'Lauren Hemp' }, outcome: 'Post', x: 101, y: 30 }),
      'Hemp lets fly from the edge… and it cracks back off the woodwork!'],
    [football(1, { clock: '28:29', players: { shooter: 'Olga Carmona García' }, outcome: 'Goal', x: 104, y: 52, score: { home: 1, away: 0 } }),
      'Olga Carmona! Low across Earps and in. Spain lead one-nil.'],
    [football(2, { clock: '69:01', period: 2, players: { shooter: 'Jennifer Hermoso Fuentes', keeper: 'Mary Earps' }, outcome: 'Saved', x: 108, y: 40, score: { home: 1, away: 0 }, detail: { shot_type: 'Penalty' } }),
      'SAVED! Earps guesses right and keeps England alive!'],
  ],
  '1298150': [
    [cricket(0, { clock: '18.5', players: { batter: 'V Kohli', bowler: 'Haris Rauf' }, outcome: '6 runs', score: { runs: 138, wickets: 4, target: 160 }, detail: { balls_left: 7 } }),
      "Kohli goes straight back over Rauf's head! Six! India need 22 off 7."],
    [cricket(1, { clock: '18.6', players: { batter: 'V Kohli', bowler: 'Haris Rauf' }, outcome: '6 runs', score: { runs: 144, wickets: 4, target: 160 }, detail: { balls_left: 6 } }),
      'And again! Flicked over fine leg. Sixteen needed off the last over.'],
    [cricket(2, { clock: '19.1', type: 'Wicket', players: { batter: 'HH Pandya', bowler: 'Mohammad Nawaz', out: 'HH Pandya' }, outcome: 'caught', score: { runs: 144, wickets: 5, target: 160 }, detail: { balls_left: 5 } }),
      'Pandya goes! Caught off Nawaz, first ball of the last over.'],
  ],
}

// Mimics the SSE stream: one moment, then its line a moment later, then end.
export function streamDemo(matchId: string, onEvent: (e: StreamEvent) => void): () => void {
  const timers: number[] = []
  const feed = feeds[matchId] ?? []
  feed.forEach(([moment, text], i) => {
    const at = 1000 + i * 4500
    timers.push(window.setTimeout(() => onEvent({ type: 'moment', moment }), at))
    const line: Line = { line_id: `demo-${matchId}-${i}`, match_id: matchId, moment_idx: moment.idx, text, latency_ms: 600, first_word_ms: 600 }
    timers.push(window.setTimeout(() => {
      onEvent({ type: 'line', line })
      onEvent({ type: 'stats', stats: demoStats(i + 1) })
    }, at + line.latency_ms))
  })
  timers.push(window.setTimeout(() => onEvent({ type: 'end' }), 1000 + feed.length * 4500))
  return () => timers.forEach(clearTimeout)
}

// Stats for the demo feed: every demo line takes 600 ms; cost and the adapter stay unknown,
// as they are on the real server until #29 lands.
export function demoStats(lines = 0): Stats {
  const ms = lines ? 600 : null
  return {
    lines, fixes: 0, mubit_requests: 0, tokens_in: 0, tokens_out: 0,
    first_word_ms_p50: ms, first_word_ms_p95: ms, latency_ms_p50: ms, latency_ms_p95: ms,
  }
}
