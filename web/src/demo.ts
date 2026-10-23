// Demo feed for building the page before the match server (#14) exists.
// Only used when the page is opened with ?demo; the real page never falls back to it.
// The lines are placeholders written by hand, not commentator output.
import type { Line, Match, Moment, StreamEvent } from './types'

export const demoMatches: Match[] = [
  { id: 'demo-wwc-2023-final', sport: 'football', title: "Women's World Cup final 2023", home: 'Spain', away: 'England' },
  { id: 'demo-ind-pak-2022', sport: 'cricket', title: 'T20 World Cup 2022', home: 'India', away: 'Pakistan' },
]

const feeds: Record<string, [Moment, string][]> = {
  'demo-wwc-2023-final': [
    [{ id: 'f1', kind: 'shot', clock: "16'", team: 'England', player: 'Lauren Hemp', x: 108, y: 34, score: '0-0' },
      'Hemp lets fly and it cannons back off the bar!'],
    [{ id: 'f2', kind: 'goal', clock: "29'", team: 'Spain', player: 'Olga Carmona', x: 104, y: 52, score: '1-0' },
      'Carmona, low across Earps and in. Spain lead!'],
    [{ id: 'f3', kind: 'save', clock: "70'", team: 'England', player: 'Mary Earps', x: 4, y: 40, score: '1-0' },
      'Earps goes the right way and saves the penalty!'],
  ],
  'demo-ind-pak-2022': [
    [{ id: 'c1', kind: 'six', clock: '18.5', team: 'India', player: 'Virat Kohli', score: 'IND 138/4' },
      'Kohli, straight back over Rauf\'s head for six!'],
    [{ id: 'c2', kind: 'six', clock: '18.6', team: 'India', player: 'Virat Kohli', score: 'IND 144/4' },
      'And again! Flicked over fine leg, sixteen needed off the last.'],
    [{ id: 'c3', kind: 'wicket', clock: '19.1', team: 'Pakistan', player: 'Mohammad Nawaz', score: 'IND 144/5' },
      'Nawaz strikes first ball, Pandya holes out.'],
  ],
}

// Mimics the SSE stream: one moment, then its line a moment later.
export function streamDemo(matchId: string, onEvent: (e: StreamEvent) => void): () => void {
  const timers: number[] = []
  const feed = feeds[matchId] ?? []
  feed.forEach(([moment, text], i) => {
    const at = 1000 + i * 4500
    timers.push(window.setTimeout(() => onEvent({ type: 'moment', moment }), at))
    const line: Line = { id: `line-${moment.id}`, moment_id: moment.id, text, latency_ms: 600 }
    timers.push(window.setTimeout(() => onEvent({ type: 'line', line }), at + line.latency_ms))
  })
  timers.push(window.setTimeout(() => onEvent({ type: 'end' }), 1000 + feed.length * 4500))
  return () => timers.forEach(clearTimeout)
}
