import { chaseText, clockText, periodText } from '../moment'
import { matchTeams, sides, type TeamStyle } from '../teams'
import type { Match, Moment } from '../types'

interface Props {
  match: Match
  moment: Moment | null
  moments: Moment[] // what the picture has reached, for the other side's innings total
}

// The score bar (docs/design.md "Components"): team bars and codes, the score, the clock and period
// (football, basketball) or the over and "need N off M" (cricket, both totals at the same weight), the
// lap and the top three (f1), and "REPLAY".
export function ScoreBar({ match, moment, moments }: Props) {
  return (
    <div className="scorebar glass" role="status">
      {match.sport === 'cricket' ? <Cricket match={match} moment={moment} moments={moments} />
        : match.sport === 'f1' ? <F1 moment={moment} />
        : <Football match={match} moment={moment} />}
      <span className="replay">REPLAY</span>
    </div>
  )
}

function Football({ match, moment }: { match: Match; moment: Moment | null }) {
  const [home, away] = matchTeams(match)
  const s = moment?.score
  return (
    <>
      <Team team={home} />
      <span className="score num">{s && 'home' in s ? `${s.home}–${s.away}` : '0–0'}</span>
      <Team team={away} />
      <span className="sep" />
      <span className="clock num">{moment ? clockText(moment) : match.sport === 'basketball' ? '12:00' : '00:00'}</span>
      <span className="period">{moment ? periodText(moment) : match.sport === 'basketball' ? 'Q1' : '1st half'}</span>
    </>
  )
}

function Cricket({ match, moment, moments }: Props) {
  const [home, away] = matchTeams(match)
  const { ours, theirs } = moment ? sides(match, moment.team) : { ours: home, theirs: away }
  const s = moment?.score
  const chase = moment ? chaseText(moment) : null
  // The fielding side's total: their last first-innings moment, else the target less one.
  const first = moments.filter((m) => m.period === 1 && m.team === theirs.name).at(-1)?.score
  const other = first && 'runs' in first ? `${first.runs}/${first.wickets}`
    : s && 'runs' in s && s.target ? String(s.target - 1) : null
  return (
    <>
      <Team team={ours} />
      <span className="score num">{s && 'runs' in s ? `${s.runs}/${s.wickets}` : '0/0'}</span>
      <Team team={theirs} />
      {moment?.period === 2 && other && <span className="score num">{other}</span>}
      <span className="sep" />
      <span className="clock num">{moment ? clockText(moment) : 'Over 0.0'}</span>
      {chase ? <span className="need num">{chase}</span> : <span className="period">{moment ? periodText(moment) : '1st innings'}</span>}
    </>
  )
}

function F1({ moment }: { moment: Moment | null }) {
  const s = moment?.score
  const top = s && 'top' in s ? s.top.slice(0, 3) : []
  return (
    <>
      <span className="clock num">{s && 'lap' in s ? `Lap ${s.lap}/${s.laps}` : 'Lap 0'}</span>
      {top.length > 0 && <span className="sep" />}
      {top.map((p) => (
        <span key={p.driver} className="team num">
          {p.pos === null ? 'PIT' : `P${p.pos}`} {p.driver}
          {p.gap && p.gap !== 'leader' && <span className="period">{shortGap(p.gap)}</span>}
        </span>
      ))}
    </>
  )
}

// The feed's gaps read aloud ("1.5 seconds", "in the pit lane"); the score bar shows them short.
function shortGap(gap: string): string {
  const s = /^([\d.]+) seconds?$/.exec(gap)
  if (s) return `+${s[1]}s`
  return gap === 'in the pit lane' ? 'pit lane' : gap
}

function Team({ team }: { team: TeamStyle }) {
  return (
    <span className="team" title={team.name} style={{ '--c': team.color } as React.CSSProperties}>
      <i />
      {team.code}
    </span>
  )
}
