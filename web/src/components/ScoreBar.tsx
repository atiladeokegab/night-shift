import { chaseText, clockText, periodText } from '../moment'
import { matchTeams, sides, type TeamStyle } from '../teams'
import type { Match, Moment } from '../types'

interface Props {
  match: Match
  moment: Moment | null
}

// The TV score bug (docs/design.md): team chips, the score between them, the clock and period, "REPLAY".
export function ScoreBar({ match, moment }: Props) {
  return (
    <div className="scorebar" aria-live="polite">
      {match.sport === 'football' ? <Football match={match} moment={moment} /> : <Cricket match={match} moment={moment} />}
      <span className="replay-tag">REPLAY</span>
    </div>
  )
}

function Football({ match, moment }: Props) {
  const [home, away] = matchTeams(match)
  const s = moment?.score
  return (
    <>
      <Chip team={home} />
      <span className="score">{s && 'home' in s ? `${s.home}–${s.away}` : '0–0'}</span>
      <Chip team={away} />
      <Clock moment={moment} />
    </>
  )
}

function Cricket({ match, moment }: Props) {
  const [home, away] = matchTeams(match)
  const { ours, theirs } = moment ? sides(match, moment.team) : { ours: home, theirs: away }
  const s = moment?.score
  const chase = moment ? chaseText(moment) : null
  return (
    <>
      <Chip team={ours} />
      <span className="score">{s && 'runs' in s ? `${s.runs}/${s.wickets}` : '–'}</span>
      <Chip team={theirs} />
      {chase && <span className="chase">{chase}</span>}
      <Clock moment={moment} />
    </>
  )
}

function Clock({ moment }: { moment: Moment | null }) {
  if (!moment) return null
  return (
    <>
      <span className="clock">{clockText(moment)}</span>
      <span className="period">{periodText(moment)}</span>
    </>
  )
}

function Chip({ team }: { team: TeamStyle }) {
  return (
    <span className="chip" title={team.name} style={{ background: team.color, color: inkOn(team.color) }}>
      {team.code}
    </span>
  )
}

// Dark letters on light chips (England's white), light letters on dark ones.
function inkOn(hex: string): string {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#0E1524' : '#FFFFFF'
}
