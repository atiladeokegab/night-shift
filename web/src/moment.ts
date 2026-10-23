// Display helpers over the contract's Moment, shared by the score bar, subtitle, line log and fields.
import type { Moment } from './types'

// The player the moment is about, by the roles data/ uses for each type.
const LEAD_ROLES = ['shooter', 'scorer', 'offender', 'out', 'batter', 'on', 'injured']

export function leadPlayer(m: Moment): string {
  for (const role of LEAD_ROLES) if (m.players[role]) return m.players[role]
  return Object.values(m.players)[0] ?? m.team
}

// A label that fits beside a stickman: long full names ("Olga Carmona García") lose the first name.
export function shortName(name: string): string {
  const words = name.split(' ')
  return name.length > 14 && words.length > 1 ? words.slice(1).join(' ') : name
}

// The design's clock: football "28:29", cricket "Over 18.5"; the line log drops the "Over".
export function clockText(m: Moment, short = false): string {
  return m.sport === 'cricket' && !short ? `Over ${m.clock}` : m.clock
}

const FOOTBALL_PERIODS = ['1st half', '2nd half', 'Extra time, 1st half', 'Extra time, 2nd half', 'Penalties']

export function periodText(m: Moment): string {
  if (m.sport === 'cricket') return m.period === 1 ? '1st innings' : '2nd innings'
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

export function isGoal(m: Moment): boolean {
  return (m.type === 'Shot' && m.outcome === 'Goal') || m.type === 'Own Goal Against'
}

export function isPenalty(m: Moment): boolean {
  return m.detail.shot_type === 'Penalty'
}

// The big amber word on the field, only for moments that have one.
export function caption(m: Moment): string | null {
  if (m.sport === 'cricket') {
    const chase = chaseText(m)
    if (chase?.endsWith(' win')) return chase.toUpperCase()
    const words: Record<string, string> = { Six: 'SIX', Four: 'FOUR', Wicket: 'WICKET', 'No ball': 'NO BALL' }
    return words[m.type] ?? null
  }
  if (m.type === 'Own Goal Against') return 'OWN GOAL'
  if (m.type === 'Shot') {
    if (m.outcome === 'Goal') return 'GOAL'
    if (m.outcome === 'Saved') return isPenalty(m) ? 'PENALTY SAVED' : 'SAVED'
    if (m.outcome === 'Post') return 'OFF THE WOODWORK'
    return isPenalty(m) ? 'PENALTY' : null
  }
  const card = cardKind(m)
  if (card) return card.toUpperCase()
  if (m.type === 'Substitution') return 'SUBSTITUTION'
  return null
}

export function cardKind(m: Moment): string | null {
  const card = String(m.detail.card ?? '')
  return card || null
}
