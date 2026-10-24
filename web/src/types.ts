// Shapes the live page reads from the match server, as docs/CONTRACT.md ("Shapes") defines them.
// api.ts is the only place that turns server JSON into these.

// PRD v5 R-10: basketball and F1 join (CONTRACT.md "Moment").
export type Sport = 'football' | 'cricket' | 'basketball' | 'f1'

export const SPORTS: Sport[] = ['football', 'cricket', 'basketball', 'f1']
export const SPORT_NAMES: Record<Sport, string> = { football: 'Football', cricket: 'Cricket', basketball: 'Basketball', f1: 'F1' }

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
  video_start?: number // the second the video starts at, just before its first mapped moment
  embed?: boolean // false: the owner blocks embedding, so a poster and a YouTube link instead
}

// Football and basketball: {home, away}; cricket: runs and wickets; f1: the lap and the top five.
export interface F1Place {
  pos: number | null // null for a car that pitted before the feed gave its new place (it comes last)
  driver: string
  gap: string // "leader", "1.5 seconds", "in the pit lane", or "" when timing lags
}

export type Score =
  | { home: number; away: number }
  | { runs: number; wickets: number; target?: number }
  | { lap: number; laps: number; top: F1Place[] }

// type: football "Shot" | "Own Goal Against" | "Foul Committed" | "Bad Behaviour" | "Substitution" |
// "Injury Stoppage" | "Full time"; cricket "Wicket" | "Six" | "Four" | "No ball" | "Last ball" | "Chase".
export interface Moment {
  sport: Sport
  match_id: string
  idx: number
  period: number // the half, the innings, the quarter (5+ is overtime) or the lap
  clock: string // "mm:ss": football, basketball (left in the quarter), f1 (since the start); "over.ball": cricket
  type: string
  team: string // cricket: the batting side
  players: Record<string, string> // role -> name: shooter, keeper, offender / batter, bowler, out
  outcome: string
  score: Score
  // A-6.4@2: seconds into the highlights video at which the moment first shows (guess asked in #47).
  video_t?: number
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
  first_word_ms?: number | null // null when the provider reported no first text word
  video_t?: number // A-6.4@2: shown and spoken when the player reaches it (#47)
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
  kept: number | null // null until the lead records it from Mubit's console (#46); never guessed
  needed: number
  agree: number | null
  total: number | null
  cost_measurable: boolean
}

// POST /lines/{line_id}/fix's answer and the `fixed` SSE event (CONTRACT.md).
export interface Fix {
  line_id: string
  corrected_text: string
  reason: string
  created_at?: number | string
  reply_matched?: boolean
}

// POST /replays/{id}/ask's answer and the `answer` SSE event (#117). `line_id` so it is spoken like a line;
// off_air: the commentator could not answer, and nothing was stored or will be spoken.
export interface Answer {
  line_id: string
  moment_idx: number
  question: string
  text: string
  off_air?: boolean
}

export type StreamEvent =
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'stats'; stats: Stats }
  | { type: 'fixed'; fix: Fix }
  | { type: 'answer'; answer: Answer }
  | { type: 'error'; detail: string }
  | { type: 'end' }

// GET /voices (A-6.3@1; PR #27's shape, agreed in #33). `browser` voices are the page's own
// speechSynthesis fallbacks, used when the server lists none.
export interface Voice {
  id: string
  label: string
  lang: string // a BCP 47 tag for the browser speech fallback, e.g. "en-IN", "en-GB"
  default_for?: Sport
  same_as?: string // the id of the entry with the same ElevenLabs voice: a sport's pick that repeats it
  browser?: boolean
}
