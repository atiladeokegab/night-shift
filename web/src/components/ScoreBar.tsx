import type { Match, Moment } from '../types'

interface Props {
  match: Match
  moment: Moment | null
  colors: { home: string; away: string }
}

export function ScoreBar({ match, moment, colors }: Props) {
  return (
    <div className="scorebar" aria-live="polite">
      <span className="team" style={{ borderColor: colors.home }}>{match.home}</span>
      <span className="score">{moment?.score ?? (match.sport === 'football' ? '0-0' : '–')}</span>
      <span className="team" style={{ borderColor: colors.away }}>{match.away}</span>
      <span className="clock">{moment ? (match.sport === 'cricket' ? `Over ${moment.clock}` : moment.clock) : 'Pre-match'}</span>
    </div>
  )
}
