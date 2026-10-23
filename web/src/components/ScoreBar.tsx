import { clockText, scoreText } from '../moment'
import type { Match, Moment } from '../types'

interface Props {
  match: Match
  moment: Moment | null
  colors: { home: string; away: string }
}

// The contract's Match has no team names and the score is {home, away}, so team names show only when
// the server sends them; otherwise the title (e.g. "Spain v England") names the sides, never a guess.
export function ScoreBar({ match, moment, colors }: Props) {
  const named = match.sport === 'football' && match.home && match.away
  return (
    <div className="scorebar" aria-live="polite">
      {named ? (
        <>
          <span className="team" style={{ borderColor: colors.home }}>{match.home}</span>
          <span className="score">{scoreText(moment, match)}</span>
          <span className="team" style={{ borderColor: colors.away }}>{match.away}</span>
        </>
      ) : (
        <>
          {match.sport === 'football' && <span className="team title">{match.title ?? match.match_id}</span>}
          <span className="score">{scoreText(moment, match)}</span>
        </>
      )}
      <span className="clock">{moment ? clockText(moment) : 'Pre-match'}</span>
    </div>
  )
}
