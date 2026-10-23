// Display helpers over the contract's Moment, shared by the score bar, subtitle and fields.
import type { Match, Moment } from './types'

// The player the moment is about, by the roles data/ uses for each type.
const LEAD_ROLES = ['shooter', 'scorer', 'offender', 'out', 'batter', 'on', 'injured']

export function leadPlayer(m: Moment): string {
  for (const role of LEAD_ROLES) if (m.players[role]) return m.players[role]
  return Object.values(m.players)[0] ?? m.team
}

export function scoreText(m: Moment | null, match: Match): string {
  if (!m) return match.sport === 'football' ? '0-0' : '–'
  const s = m.score
  if ('home' in s) return `${s.home}-${s.away}`
  return `${m.team} ${s.runs}/${s.wickets}${s.target ? ` · target ${s.target}` : ''}`
}

export function clockText(m: Moment): string {
  if (m.sport === 'cricket') return `Over ${m.clock}`
  // StatsBomb counts from 00:00, broadcasts from the 1st minute: 28:21 is the 29th minute.
  const minute = Number(m.clock.split(':')[0]) + 1
  return Number.isFinite(minute) ? `${minute}'` : m.clock
}

export function isGoal(m: Moment): boolean {
  return (m.type === 'Shot' && m.outcome === 'Goal') || m.type === 'Own Goal Against'
}

export function cardColor(m: Moment): string | null {
  const card = String(m.detail.card ?? '')
  if (!card) return null
  return card.startsWith('Yellow') ? '#ffd23f' : '#ff3b30'
}

// Two colours for two sides. The match header names home when data/ sends it; otherwise the first
// team seen in the replay takes the home colour, so a side keeps its colour all match.
export function sideOf(team: string, match: Match, firstTeam: string | null): 'home' | 'away' {
  const home = match.home ?? firstTeam
  return !home || team === home ? 'home' : 'away'
}
