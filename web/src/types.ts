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
  peak_idx?: number // "Jump to the big moment" (#163) starts the replay at this moment
  peak_video_start?: number // and the video at this second
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
  speaker?: 'lead' | 'analyst' // #130: the moment's call, or a stat line between moments; none is the lead
  history?: boolean // #163: said in an earlier replay, before a jump's moment: shown, never spoken
  fixed?: boolean // #232: said in a producer's fixed words, not called; `fix_id` is the line it fixed
  fix_id?: string
  served_by?: string | null // #250: the model Mubit's reply said answered; none before #250 or offline
  fill?: boolean // #297: the extra pair in a long quiet, dropped if the next moment comes first
  retried?: boolean // #338: the first call failed the number check and the retry passed: auto-fixed
}

// GET /stats and the `stats` SSE event (CONTRACT.md); percentiles are null until there is a line.
// cost_per_line_usd is null until a line has a cost; adapter.state is collecting until a version is recorded.
// GET /stats `voice` (#306): who speaks the lines, and ElevenLabs' last failure while it is failing.
export interface VoiceHealth {
  provider: 'elevenlabs' | 'browser'
  last_error: string | null // e.g. "quota_exceeded", "timeout", "429"
  since: string | null // ISO time the failing began
}

export interface Stats {
  voice?: VoiceHealth // GET /stats only: the `stats` event leaves it out
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
  by_speaker?: { lead: SpeakerStats; analyst: SpeakerStats } // #161: Haiku's calls apart from Sonnet's stat lines
  fixes_recorded?: number // fixes Mubit recorded for training; `fixes` counts every stored fix
  fixes_toward_next?: number // recorded fixes since the latest adapter record (#161)
  spoken_from_fix?: number // lines a replay said in a producer's fixed words, not the model's (#232)
  // #174: a full replay's mean spend over matches_measured of them; null when it can't be measured
  matches_measured?: number
  cost_per_match_usd?: number | null
  model_cost_per_match_usd?: number | null
  voice_cost_per_match_usd?: number | null
  // #204: the lead's calls by how the number check left them, over every match and per match_id
  autonomy?: Autonomy
  autonomy_by_match?: Record<string, Autonomy>
  linecheck?: LineCheckStats // #298
  scorecheck?: ScoreCheckStats // #321
  earlier_tasks?: EarlierTasks // #363
}

// #363: the commentary tasks trained before Score check: commentary's summary and each other task's latest record
export interface EarlierTasks {
  adapter: Adapter
  adapters: Record<string, TaskAdapter> // #209: by task, never score_check
}

// #321: Score check's examples sent to Mubit, and each model's latest score on its frozen held-out lines
export interface ScoreCheckStats {
  examples_sent: number
  by_source: { answer_key: number; auto_fixed: number; human: number } // #363
  from_fixes_by_kind: Record<string, number>
  held_out: Record<string, { agree: number; scored: number; unparsed: number; recorded_at: string | null }> // by model
  next_training: string // #363, e.g. "after 01:00 UK"
  recorded: TaskAdapter | null // #363: the last version read off the console by hand; null until then
}

// #298: Line check's second opinion on live lead lines; every flag is on a line the rules check passed
export interface LineCheckStats {
  checked: number
  flags: number
  rules_missed: number
  fixes_sent: number // producer fixes sent to Line check as examples
  examples_today?: number // #305: those sent today (UTC)
  examples_today_by_kind?: Record<string, number>
  heldout?: HeldOut | null // #317: null until eval/linecheck_heldout.json is committed
}

// #317: eval/linecheck_eval.py --json on the held-out labels: each check's catches and false alarms
export interface HeldOut {
  labels: string
  lines: number
  wrong: number
  rules: { caught: number; false_alarms: number }
  line_check: { caught: number; false_alarms: number }
  errors: number
}

// #305: GET /lines/{id} → `linecheck_example`, the Line check example a producer's fix sent
export interface LineCheckExample {
  line_id: string
  kind: 'matched' | 'corrected' | 'uncorrected' | 'leader_only' | 'error'
  mubit_request_id: string | null
  created_at: string
}

// GET /lines/{id}'s `scorecheck_examples` (#392, #400): a Score check example a fix of the line sent,
// the line as said or the fixed text, each labelled from the event data
export interface ScoreCheckExample {
  line_id: string
  text: string
  gold: 'ok' | 'wrong' | 'not_said'
  kind: 'matched' | 'corrected' | 'uncorrected'
  mubit_request_id: string | null
  created_at: string
}

// The `linecheck` SSE event (#298): Line check's answer on one line. labels null: no canonical reply.
export interface LineCheck {
  line_id: string
  labels: Record<'score' | 'leader' | 'player_total' | 'event', 'ok' | 'wrong' | 'not_said'> | null
  wrong: string[]
}

// called = first_time + auto_fixed + to_human: passed the check, fixed by the retry, or the retry failed
// too, so the line built from the match data was said and the try waits in Review for a person
export interface Autonomy {
  called: number
  first_time: number
  auto_fixed: number
  to_human: number
}

// GET /review (#171): a stored lead line the number check flags, with its moment, for the producer to fix.
export interface ReviewItem {
  line_id: string
  match_id: string
  match: string // the match's title
  sport: Sport
  moment_idx: number
  clock: string | null
  period: number | null
  score: string
  play: string
  text: string
  wrong: string[] // what the number check found, e.g. "58 is not in the moment"
  lines: number // how many wordings of this mistake (same match, moment and reasons) were said (#227)
  others: string[] // the older wordings, newest first; one fix clears them all
  later_check: boolean // said before today's check, which fails it; false: its retry failed as it was said
}

export interface SpeakerStats {
  model: string // the models seen, comma-separated
  served_by?: string // #250: the models Mubit said answered, comma-separated; '' before #250
  served_lines?: number // #250: the lines that carry a served_by; older and data-built lines don't
  lines: number
  first_word_ms_p50: number | null
  first_word_ms_p95: number | null
  cost_per_line_usd: number | null
}

export type AdapterState = 'collecting' | 'testing' | 'passed' // what the record shows; passed only if Mubit's gate said so

export interface Adapter {
  state: AdapterState
  summary: string // e.g. "Testing: no version passed; best 55.8% of a 95% target, as of 24 Oct 2026 13:04 UTC."
  kept: number | null // null until the lead records it from Mubit's console (#46); never guessed
  agree: number | null
  total: number | null
  cost_measurable: boolean
  console?: ConsoleReading | null // #317: data/mubit_console.json, a dated hand reading, never live
}

// #317: Mubit's console overview as read by hand on `read_at`, and the tasks it listed
export interface ConsoleReading {
  source: string
  read_at: string // ISO, UTC
  tasks: number
  adapters: number
  serving: number
  target: number
  listed: Record<string, { status: string; examples: number; quality: number }> // by task name: no brackets in a `stats` event
}

// One Mubit task's latest adapter record (#209), as the lead read it off Mubit's console; null where it didn't say.
export interface TaskAdapter {
  state: AdapterState
  version: number | null
  score: number | null // "matched N% of the provider model's answers", 0 to 100
  target: number | null // the console's target for score, e.g. 95
  passed: boolean | null // Mubit's gate: Passed or Failed
  kept: number | null // Mubit's kept examples from the console, never requests sent
  recorded_at: string | null
  version_id?: string | null // #321: the version's ID as the console shows it
  source?: string | null // #321: where the record was read, e.g. "Mubit console"
  versions?: TaskVersion[] // #321: every version recorded, oldest first
}

export interface TaskVersion {
  version: number
  version_id: string | null
  score: number | null
  target: number | null
  passed: boolean | null
  recorded_at: string | null
  source: string | null
}

// POST /lines/{line_id}/fix's answer and the `fixed` SSE event (CONTRACT.md).
export interface Fix {
  line_id: string
  corrected_text: string
  reason: string
  created_at?: number | string
  correction?: string // the exact turn Mubit was given after the wrong line (#245)
  reply_passed?: boolean // the commentator's corrected reply passed the number check
  recorded?: boolean // Mubit recorded it for training (#161)
  mubit_request_id?: string | null // the correction call's request id (#239)
}

// POST /replays/{id}/ask's answer and the `answer` SSE event (#117). `line_id` so it is spoken like a line;
// off_air: the commentator could not answer, and nothing was stored or will be spoken.
export interface Answer {
  line_id: string
  moment_idx: number
  question: string
  text: string
  off_air?: boolean
  notice?: string // off air on purpose (#244): the page shows this, not its calm try-again copy
}

export type StreamEvent =
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'stats'; stats: Stats }
  | { type: 'fixed'; fix: Fix }
  | { type: 'linecheck'; check: LineCheck }
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
  analyst_for?: Sport[] // the sports whose analyst lines this voice reads (core/voice.py analyst_voice)
  browser?: boolean
}

// GET /ledger: one correction sent to Mubit, with the session and request to find it in the console.
export interface LedgerRow {
  at: string | null
  task: 'Score check' | 'Commentator'
  source: string // "answer key", "human" or "auto-fixed"
  match: string | null
  idx: number | null
  text: string | null
  score: string | null // the data's score at the moment
  wrong: string[] // what the number check finds wrong in the line
  session: string | null
  request_id: string | null
  link: string | null // Mubit's console, once its URL is known
}

export interface Ledger {
  sent: number // examples sent to Score check
  rows: LedgerRow[] // the newest 50 corrections
}

// GET /teams/{sport}/{match_id} (#375): the graph's view of both sides before the match; sections may be empty.
export interface TeamGame {
  date: string
  opponent: string
  home: boolean
  score: string
  result: string // W, D, L, or another code a sport uses
}
export interface TeamInfo {
  team: string
  form: TeamGame[]
  squad: { name: string; matches: number; headline: string }[]
}
export interface Teams {
  teams: TeamInfo[]
  head_to_head: TeamGame[]
}
