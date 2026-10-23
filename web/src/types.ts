// Shapes the live page reads from the match server.
// Guessed from issue #18 until docs/CONTRACT.md is filled in (#14); api.ts is the only place
// that turns server JSON into these, so a contract change lands there.

export type Sport = 'football' | 'cricket'

export interface Match {
  id: string
  sport: Sport
  title: string
  home: string
  away: string
}

// Football kinds come from StatsBomb event types, cricket kinds from Cricsheet deliveries.
export type MomentKind =
  | 'shot'
  | 'goal'
  | 'save'
  | 'card'
  | 'wicket'
  | 'four'
  | 'six'
  | 'other'

export interface Moment {
  id: string
  kind: MomentKind
  clock: string // "29'" in football, "18.5" (over.ball) in cricket
  team: string
  player: string
  // Football only: StatsBomb pitch coordinates, x 0-120 left to right, y 0-80 top to bottom.
  x?: number
  y?: number
  score: string // already formatted by the server: "1-0", "IND 144/4"
}

export interface Line {
  id: string // POST /lines/{id}/fix targets it
  moment_id: string
  text: string
  latency_ms: number
}

export type StreamEvent =
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'end' }
