import type { Moment } from '../types'
import { Stickman } from './Stickman'

interface Props {
  moment: Moment | null
  bat: string // colour of the batting side, the moment's team in cricket
  field: string
  label: string
}

// Cricsheet has no field positions, so the ground is staged by the kind of delivery:
// batter and bowler on the strip, fielders on a ring, the ball sent where the moment says.
const FIELDERS: [number, number][] = [
  [30, 30], [90, 30], [20, 55], [100, 55], [32, 82], [88, 82], [60, 16], [60, 90], [45, 70],
]

export function Ground({ moment, bat, field, label }: Props) {
  const type = moment?.type
  const boundary = type === 'Four' || type === 'Six'
  const ball = ballSpot(moment)

  return (
    <svg className="field" viewBox="0 0 120 100" role="img" aria-label={`${label}: cricket ground`}>
      <g className="markings" fill="none">
        <ellipse cx={60} cy={50} rx={58} ry={48} />
        <ellipse cx={60} cy={50} rx={30} ry={25} strokeDasharray="1.5 1.5" />
        <rect className="strip" x={56} y={38} width={8} height={24} />
      </g>
      {FIELDERS.map(([fx, fy], i) => <Stickman key={i} x={fx} y={fy} color={field} faded />)}
      <Stickman x={60} y={68} color={field} faded />
      <Stickman x={58} y={38} color={field} pose={type === 'Wicket' ? 'cheer' : 'bowl'} />
      <Stickman x={61} y={62} color={bat} pose={boundary ? 'cheer' : 'bat'} />
      {type === 'Wicket' && <path className="stumps-broken" d="M58.6 63 L58 60 M60 63 L61 60.2 M61.4 63 L62.6 60.6" />}
      <circle className="ball" r={1} style={{ transform: `translate(${ball[0]}px, ${ball[1]}px)` }} />
    </svg>
  )
}

// Boundaries go to one of a few spots on the rope, picked from the moment's index so a replay looks the same.
const ROPE: [number, number][] = [[60, 3], [108, 30], [112, 66], [20, 80], [10, 40]]
const INFIELD: [number, number][] = [[44, 34], [78, 46], [70, 70], [40, 58]]

function ballSpot(moment: Moment | null): [number, number] {
  if (!moment) return [59, 40]
  if (moment.type === 'Six' || moment.type === 'Four') {
    const [x, y] = ROPE[moment.idx % ROPE.length]
    return moment.type === 'Six' ? [x, y] : [x * 0.96 + 2.4, y * 0.96 + 2]
  }
  if (moment.type === 'Wicket') return [60, 63]
  return INFIELD[moment.idx % INFIELD.length]
}
