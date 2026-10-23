// Demo feed for building the page without the match server: only used with ?demo, never as a fallback.
// Moments follow the contract's shapes; the lines are placeholders written by hand, not commentator output.
import type { Line, Match, Moment, StreamEvent } from './types'

export const demoMatches: Match[] = [
  { match_id: 'demo-football', sport: 'football', title: "Women's World Cup final 2023", sample: true, home: 'Spain', away: 'England' },
  { match_id: 'demo-cricket', sport: 'cricket', title: 'T20 World Cup 2022', sample: true, home: 'India', away: 'Pakistan' },
]

const football = (idx: number, m: Partial<Moment>): Moment => ({
  sport: 'football', match_id: 'demo-football', idx, period: 1, clock: '00:00', type: 'Shot', team: '',
  players: {}, outcome: '', score: { home: 0, away: 0 }, detail: {}, ...m,
})
const cricket = (idx: number, m: Partial<Moment>): Moment => ({
  sport: 'cricket', match_id: 'demo-cricket', idx, period: 2, clock: '0.0', type: 'Six', team: 'India',
  players: {}, outcome: '', score: { runs: 0, wickets: 0, target: 160 }, detail: {}, ...m,
})

const feeds: Record<string, [Moment, string][]> = {
  'demo-football': [
    [football(0, { clock: '15:40', team: 'England', players: { shooter: 'Lauren Hemp' }, outcome: 'Post', x: 108, y: 34 }),
      'Hemp lets fly and it cannons back off the bar!'],
    [football(1, { clock: '28:21', team: 'Spain', players: { shooter: 'Olga Carmona' }, outcome: 'Goal', x: 104, y: 52, score: { home: 1, away: 0 } }),
      'Carmona, low across Earps and in. Spain lead!'],
    [football(2, { clock: '69:30', period: 2, team: 'Spain', players: { shooter: 'Jennifer Hermoso', keeper: 'Mary Earps' }, outcome: 'Saved', x: 108, y: 40, score: { home: 1, away: 0 } }),
      'Hermoso from the spot, and Earps saves it!'],
  ],
  'demo-cricket': [
    [cricket(0, { clock: '18.5', players: { batter: 'Virat Kohli', bowler: 'Haris Rauf' }, outcome: '6 runs', score: { runs: 138, wickets: 4, target: 160 } }),
      'Kohli, straight back over Rauf\'s head for six!'],
    [cricket(1, { clock: '18.6', players: { batter: 'Virat Kohli', bowler: 'Haris Rauf' }, outcome: '6 runs', score: { runs: 144, wickets: 4, target: 160 } }),
      'And again! Flicked over fine leg, sixteen needed off the last.'],
    [cricket(2, { clock: '19.1', type: 'Wicket', players: { batter: 'Hardik Pandya', bowler: 'Mohammad Nawaz', out: 'Hardik Pandya' }, outcome: 'caught', score: { runs: 144, wickets: 5, target: 160 } }),
      'Nawaz strikes first ball, Pandya holes out.'],
  ],
}

// Mimics the SSE stream: one moment, then its line a moment later, then end.
export function streamDemo(matchId: string, onEvent: (e: StreamEvent) => void): () => void {
  const timers: number[] = []
  const feed = feeds[matchId] ?? []
  feed.forEach(([moment, text], i) => {
    const at = 1000 + i * 4500
    timers.push(window.setTimeout(() => onEvent({ type: 'moment', moment }), at))
    const line: Line = { line_id: `demo-${matchId}-${i}`, match_id: matchId, moment_idx: moment.idx, text, latency_ms: 600 }
    timers.push(window.setTimeout(() => onEvent({ type: 'line', line }), at + line.latency_ms))
  })
  timers.push(window.setTimeout(() => onEvent({ type: 'end' }), 1000 + feed.length * 4500))
  return () => timers.forEach(clearTimeout)
}
