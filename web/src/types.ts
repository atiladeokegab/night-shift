// Shapes the live page reads from the match server, as docs/CONTRACT.md ("Shapes") defines them.
// api.ts is the only place that turns server JSON into these.

export type Sport = 'football' | 'cricket'

export interface Match {
  match_id: string
  sport: Sport
  title?: string
  sample: boolean
  // Not in the contract's Match, but data/'s match header has them; used when present.
  home?: string
  away?: string
}

export type Score = { home: number; away: number } | { runs: number; wickets: number; target?: number }

// type: football "Shot" | "Own Goal Against" | "Foul Committed" | "Bad Behaviour" | "Substitution" |
// "Injury Stoppage"; cricket "Wicket" | "Six" | "Four" | "No ball" | "Last ball" | "Chase".
export interface Moment {
  sport: Sport
  match_id: string
  idx: number
  period: number
  clock: string // "mm:ss" in football, "over.ball" in cricket
  type: string
  team: string // cricket: the batting side
  players: Record<string, string> // role -> name: shooter, keeper, offender / batter, bowler, out
  outcome: string
  score: Score
  x?: number // StatsBomb 120 x 80, when known
  y?: number
  detail: Record<string, unknown>
}

export interface Line {
  line_id: string
  match_id: string
  moment_idx: number
  text: string
  latency_ms: number
  first_word_ms?: number
}

export type StreamEvent =
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'error'; detail: string }
  | { type: 'end' }
