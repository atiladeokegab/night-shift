// Display helpers over the contract's Moment, shared by the score bar and the line log.
import type { Moment } from './types'

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
