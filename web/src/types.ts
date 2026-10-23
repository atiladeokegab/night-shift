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
  // PRD v2 (A-6.1@2, A-6.4@1): the match's official highlights, from data/video/ (#33).
  youtube_id?: string
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

// GET /stats and the `stats` SSE event (CONTRACT.md); percentiles are null until there is a line.
// cost_per_line_usd and adapter are proposed in #29 and absent until core sends them.
export interface Stats {
  lines: number
  fixes: number
  mubit_requests: number
  first_word_ms_p50: number | null
  first_word_ms_p95: number | null
  latency_ms_p50: number | null
  latency_ms_p95: number | null
  tokens_in: number
  tokens_out: number
  cost_per_line_usd?: number | null
  adapter?: Adapter | null
}

export interface Adapter {
  status: 'not_trained' | 'training' | 'ready'
  kept: number
  needed: number
  agree: number | null
  total: number | null
  cost_measurable: boolean
}

export type StreamEvent =
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'stats'; stats: Stats }
  | { type: 'error'; detail: string }
  | { type: 'end' }

// GET /voices (A-6.3@1; PR #27's shape, agreed in #33). `browser` voices are the page's own
// speechSynthesis fallbacks, used when the server lists none.
export interface Voice {
  id: string
  label: string
  lang: string // a BCP 47 tag for the browser speech fallback, e.g. "en-IN", "en-GB"
  default_for?: Sport
  browser?: boolean
}
