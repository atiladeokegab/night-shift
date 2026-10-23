import { clockText, scoreText } from '../moment'
import type { Match, Moment } from '../types'

interface Props {
  match: Match
  moment: Moment | null
  names: { home: string; away: string }
  colors: { home: string; away: string }
}

export function ScoreBar({ match, moment, names, colors }: Props) {
  return (
    <div className="scorebar" aria-live="polite">
      {match.sport === 'football' ? (
        <>
          <span className="team" style={{ borderColor: colors.home }}>{names.home}</span>
          <span className="score">{scoreText(moment, match)}</span>
          <span className="team" style={{ borderColor: colors.away }}>{names.away}</span>
        </>
      ) : (
        <span className="score">{scoreText(moment, match)}</span>
      )}
      <span className="clock">{moment ? clockText(moment) : 'Pre-match'}</span>
    </div>
  )
}
