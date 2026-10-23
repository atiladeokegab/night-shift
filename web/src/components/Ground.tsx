import { caption, shortName } from '../moment'
import type { Moment } from '../types'
import { BallPath } from './BallPath'
import { Stickman } from './Stickman'

interface Props {
  moment: Moment | null
  bat: string // colour of the batting side, the moment's team in cricket
  field: string
  label: string
}

// Cricsheet has no field positions, so the ground is staged by the kind of delivery: bowler and
// batter on the strip, the ball's path sent where the moment says.
export function Ground({ moment, bat, field, label }: Props) {
  const type = moment?.type
  const boundary = type === 'Four' || type === 'Six'
  const word = moment ? caption(moment) : null
  const key = moment ? `${moment.match_id}-${moment.idx}` : 'none'
  const batter = moment?.players.batter
  const bowler = moment?.players.bowler

  return (
    <svg className="field" viewBox="0 0 120 100" role="img" aria-label={`${label}: cricket ground`}>
      <g className="markings">
        <ellipse cx={60} cy={50} rx={56} ry={46} />
        <ellipse cx={60} cy={50} rx={28} ry={23} strokeDasharray="1.5 1.5" />
      </g>
      <rect className="strip" x={56} y={38} width={8} height={24} />
      {type === 'Wicket' && <path className="stumps-broken" d="M58.6 63 L58 60 M60 63 L61 60.2 M61.4 63 L62.6 60.6" />}
      <Stickman x={59} y={40} color={field} pose={type === 'Wicket' ? 'cheer' : 'bowl'}
        label={bowler ? shortName(bowler) : undefined} />
      <Stickman x={60} y={62} color={bat} pose={boundary ? 'cheer' : 'bat'}
        label={batter ? shortName(batter) : undefined} labelBelow />
      {moment && type !== 'Wicket' && <BallPath key={key} id={key} from={[61.5, 55]} to={ballEnd(moment)} />}
      {word && <text key={`c${key}`} className="caption" x={60} y={93} textAnchor="middle">{word}</text>}
    </svg>
  )
}

// Boundaries go to one of a few spots on the rope, picked from the moment's index so a replay looks the same.
const ROPE: [number, number][] = [[68, 5], [108, 30], [112, 66], [22, 80], [10, 38]]
const INFIELD: [number, number][] = [[42, 36], [80, 46], [72, 72], [40, 60]]

function ballEnd(m: Moment): [number, number] {
  if (m.type === 'Six' || m.type === 'Four') {
    const [x, y] = ROPE[m.idx % ROPE.length]
    return m.type === 'Six' ? [x, y] : [x * 0.95 + 3, y * 0.95 + 2.5]
  }
  return INFIELD[m.idx % INFIELD.length]
}
