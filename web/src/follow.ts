// GET /replays/{id}/players (#140): everyone in the match, those the moments so far name first.
export interface Player {
  name: string
  team: string | null
  record: boolean // a pre-match record in the pack
  named: boolean // named in a moment so far
}

type Zone = { zone: string; attempts: number; made: number }
type Phase = { balls: number; runs: number; outs: number }
type Phases = Record<'powerplay' | 'middle' | 'death', Phase>

// GET /replays/{id}/players/{name}/profile (#140): the record before tonight and tonight up to the
// moment on screen. `before` is null with no pre-match record; its shape follows the sport.
export interface Profile {
  player: string
  team: string | null
  sport: 'basketball' | 'football' | 'cricket' | 'f1'
  window: { from: string; to: string }
  before: {
    games: number
    attempts?: number; made?: number; xg?: number; zones?: Zone[]
    batting?: Phases; bowling?: { balls: number; runs: number; wickets: number; economy: number | null }
    wins?: number; finishes?: number; avg_finish?: number; avg_gained?: number
  } | null
  tonight: {
    attempts?: number; made?: number; xg?: number; zones?: Zone[]
    batting?: Phases; bowling?: { balls: number; runs: number; wickets: number }
    laps?: { lap: number; pos: number }[]
  }
  n: number
  small_sample: boolean
  text: string
}

export const PHASES = ['powerplay', 'middle', 'death'] as const

// Lower case without accents, like the server's find(): "mbappe" finds "Kylian Mbappé".
export const fold = (s: string) => s.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().trim()

// The picker's list: every word of the query in the name or the team, in the server's order.
export function search(players: Player[], query: string, limit = 8): Player[] {
  const words = fold(query).split(/\s+/).filter(Boolean)
  return players.filter((p) => words.every((w) => fold(`${p.name} ${p.team ?? ''}`).includes(w))).slice(0, limit)
}

// A line is the followed player's when its words name them: their surname ("Messi", "Kohli", "Di María"
// by "maría"), accents ignored. A line about their team that never names them is not theirs.
export function names(text: string | undefined, followed: string | null | undefined): boolean {
  const surname = followed ? fold(followed).split(/\s+/).at(-1) : ''
  return !!text && !!surname && fold(text).split(/[^\p{L}\p{N}]+/u).includes(surname)
}

const many = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`
const pct = (made: number, att: number) => (att ? ` (${Math.round((made / att) * 100)}%)` : '')
const runs = (b: Phases) => PHASES.reduce((a, ph) => ({ balls: a.balls + b[ph].balls, runs: a.runs + b[ph].runs }), { balls: 0, runs: 0 })

// "Before tonight" in one line, or null with no record.
export function recordLine(p: Profile): string | null {
  const b = p.before
  if (!b) return null
  if (p.sport === 'f1') return `${b.wins} wins in ${b.games} races, average finish ${b.avg_finish}`
  if (p.sport === 'cricket') {
    const bat = runs(b.batting!)
    const bowl = b.bowling!.balls ? `, ${b.bowling!.wickets} wickets in ${b.bowling!.balls} balls` : ''
    return `${bat.runs} runs off ${bat.balls} balls${bowl} in ${b.games} games`
  }
  if (p.sport === 'football') return `${many(b.made!, 'goal')} from ${many(b.attempts!, 'shot')}, ${b.xg} xG in ${b.games} games`
  return `${b.made} of ${b.attempts}${pct(b.made!, b.attempts!)} in ${b.games} games`
}

// Tonight so far in one line.
export function tonightLine(p: Profile): string {
  const t = p.tonight
  if (p.sport === 'f1') {
    const last = t.laps?.at(-1)
    return last ? `P${last.pos} on lap ${last.lap}` : 'Not in the top five yet'
  }
  if (p.sport === 'cricket') {
    const bat = runs(t.batting!)
    const bowl = t.bowling!.balls ? ` · ${t.bowling!.wickets} for ${t.bowling!.runs} off ${t.bowling!.balls}` : ''
    return `${bat.runs} off ${bat.balls}${bowl}`
  }
  if (p.sport === 'football') return `${many(t.made!, 'goal')} from ${many(t.attempts!, 'shot')}, ${t.xg} xG`
  return `${t.made} of ${t.attempts}${pct(t.made!, t.attempts!)}`
}

// The card's caveat: no record at all, or a record too small to lean on (n < 10).
export function sampleNote(p: Profile): string | null {
  if (!p.before) return 'No pre-match record: tonight only'
  if (!p.small_sample) return null
  const unit = p.sport === 'f1' ? 'race' : p.sport === 'cricket' ? 'ball' : p.sport === 'football' ? 'shot' : 'attempt'
  return `Small sample: ${many(p.n, unit)} before tonight`
}

// An answer kept with what it was asked for (the #128 lesson): it shows only for the same replay and
// player, and only while the moment on screen is at or past the one it was cut at, so a rewind, a
// player switch, a replay switch or a late answer never shows tonight's later stats or someone else's.
export type Asked<T> = { replay: number; name: string; momentIdx: number; value: T | 'error' }
export function answerFor<T>(got: Asked<T> | null, replay: number, name: string, momentIdx: number): T | 'error' | 'loading' {
  if (!got || got.replay !== replay || got.name !== name || got.momentIdx > momentIdx) return 'loading'
  return got.value
}
