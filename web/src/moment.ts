// Display helpers over the contract's Moment, shared by the score bar, subtitle and line log.
import type { Line, Moment } from './types'

// A video match's cold open (#221) is a Stat moment with the first mapped moment's idx, and an analyst's
// stat line has the idx of the moment it follows: the video time tells them apart (the cold open has none).
export const sameMoment = (a: Pick<Moment, 'idx' | 'video_t'>, b: Pick<Moment, 'idx' | 'video_t'>) =>
  a.idx === b.idx && a.video_t === b.video_t

// The moment a line was said over: the one with its idx and video time, else the first with its idx.
export const momentOf = <M extends Pick<Moment, 'idx' | 'video_t'>>(moments: M[], l: Pick<Line, 'moment_idx' | 'video_t'>): M | undefined =>
  moments.find((m) => sameMoment(m, { idx: l.moment_idx, video_t: l.video_t })) ?? moments.find((m) => m.idx === l.moment_idx)

// The design's clock: football "28:29", cricket "Over 18.5" (the line log drops the "Over"); basketball
// the time left in the quarter; f1 the lap.
export function clockText(m: Moment, short = false): string {
  if (m.sport === 'cricket') return short ? m.clock : `Over ${m.clock}`
  if (m.sport === 'f1') return `Lap ${m.period}`
  return m.clock
}

const FOOTBALL_PERIODS = ['1st half', '2nd half', 'Extra time, 1st half', 'Extra time, 2nd half', 'Penalties']

export function periodText(m: Moment): string {
  if (m.sport === 'cricket') return m.period === 1 ? '1st innings' : '2nd innings'
  if (m.sport === 'basketball') return m.period <= 4 ? `Q${m.period}` : m.period === 5 ? 'OT' : `OT${m.period - 4}`
  if (m.sport === 'f1') return 'score' in m && 'laps' in m.score ? `of ${m.score.laps}` : ''
  return FOOTBALL_PERIODS[m.period - 1] ?? ''
}

// Cricket chase: "need 22 off 7", or the winning side once the target is reached.
export function chaseText(m: Moment): string | null {
  const s = m.score
  if (!('runs' in s) || !s.target) return null
  if (s.runs >= s.target) return `${m.team} win`
  const balls = m.detail.balls_left
  return typeof balls === 'number' ? `need ${s.target - s.runs} off ${balls}` : `need ${s.target - s.runs}`
}

const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

// What the moment was, in the design's words ("Moment tag"): "Goal", "Penalty", "Off the woodwork",
// "Stoppage", "Six", "Wicket", "No-ball · Six", "India win".
export function momentName(m: Moment): string {
  if (m.sport === 'basketball' || m.sport === 'f1') return sentence(m.outcome || m.type)
  if (m.sport === 'cricket') {
    const chase = chaseText(m)
    if (chase?.endsWith(' win')) return chase
    if (m.type === 'No ball') return m.detail.runs_batter === 6 ? 'No-ball · Six' : m.detail.runs_batter === 4 ? 'No-ball · Four' : 'No-ball'
    if (m.type === 'Six' || m.type === 'Four' || m.type === 'Wicket') return m.type
    return sentence(m.outcome || m.type)
  }
  if (m.type === 'Own Goal Against') return 'Own goal'
  if (m.type === 'Shot') {
    if (m.outcome === 'Goal') return 'Goal'
    if (m.detail.shot_type === 'Penalty') return m.outcome === 'Saved' ? 'Penalty saved' : 'Penalty'
    if (m.outcome === 'Post') return 'Off the woodwork'
    if (m.outcome === 'Saved') return 'Saved'
    return 'Shot'
  }
  if (m.detail.card) return sentence(String(m.detail.card).toLowerCase())
  if (m.type === 'Injury Stoppage') return 'Stoppage'
  return sentence(m.type.toLowerCase())
}

// The lower third's name: the moment's first named player (shooter, batter, offender); a stat or the final whistle has none.
export const calledPlayer = (m: Moment): string | undefined => Object.values(m.players ?? {})[0] || undefined

// The tag above the subtitle: "28:29 · Goal", "Over 19.4 · No-ball · Six".
export function momentTag(m: Moment): string {
  return `${clockText(m)} · ${momentName(m)}`
}
