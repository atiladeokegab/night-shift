import type { Match, Moment } from '../types'
import { Stickman } from './Stickman'

interface Props {
  match: Match
  moment: Moment | null
  colors: { home: string; away: string }
}

// Cricsheet has no field positions, so the ground is staged by the kind of delivery:
// batter and bowler on the strip, fielders on a ring, the ball sent where the moment says.
const FIELDERS: [number, number][] = [
  [30, 30], [90, 30], [20, 55], [100, 55], [32, 82], [88, 82], [60, 16], [60, 90], [45, 70],
]

export function Ground({ match, moment, colors }: Props) {
  const batting = battingTeam(match, moment)
  const bat = batting === match.home ? colors.home : colors.away
  const field = batting === match.home ? colors.away : colors.home
  const kind = moment?.kind
  const ball = ballSpot(moment)

  return (
    <svg className="field" viewBox="0 0 120 100" role="img" aria-label={`${match.title}: cricket ground`}>
      <g className="markings" fill="none">
        <ellipse cx={60} cy={50} rx={58} ry={48} />
        <ellipse cx={60} cy={50} rx={30} ry={25} strokeDasharray="1.5 1.5" />
        <rect className="strip" x={56} y={38} width={8} height={24} />
      </g>
      {FIELDERS.map(([fx, fy], i) => <Stickman key={i} x={fx} y={fy} color={field} faded />)}
      <Stickman x={60} y={68} color={field} faded />
      <Stickman x={58} y={38} color={field} pose={kind === 'wicket' ? 'cheer' : 'bowl'} />
      <Stickman x={61} y={62} color={bat} pose={kind === 'four' || kind === 'six' ? 'cheer' : 'bat'} />
      {kind === 'wicket' && <path className="stumps-broken" d="M58.6 63 L58 60 M60 63 L61 60.2 M61.4 63 L62.6 60.6" />}
      <circle className="ball" r={1} style={{ transform: `translate(${ball[0]}px, ${ball[1]}px)` }} />
    </svg>
  )
}

// The moment names the player who made it: a wicket is the fielding side's, a boundary the batter's.
function battingTeam(match: Match, moment: Moment | null): string {
  if (!moment) return match.home
  if (moment.kind === 'wicket') return moment.team === match.home ? match.away : match.home
  return moment.team
}

// Boundaries go to one of a few spots on the rope, picked from the moment id so a replay looks the same.
const ROPE: [number, number][] = [[60, 3], [108, 30], [112, 66], [20, 80], [10, 40]]

function ballSpot(moment: Moment | null): [number, number] {
  if (!moment) return [59, 40]
  if (moment.kind === 'six' || moment.kind === 'four') {
    const [x, y] = ROPE[hash(moment.id) % ROPE.length]
    return moment.kind === 'six' ? [x, y] : [x * 0.96 + 2.4, y * 0.96 + 2]
  }
  if (moment.kind === 'wicket') return [60, 63]
  return [60, 58]
}

function hash(s: string): number {
  let h = 0
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return h
}
