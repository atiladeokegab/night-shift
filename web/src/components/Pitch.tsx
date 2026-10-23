import { caption, cardKind, isGoal, leadPlayer, shortName } from '../moment'
import type { Moment } from '../types'
import { BallPath } from './BallPath'
import { Stickman, type Pose } from './Stickman'

interface Props {
  moment: Moment | null
  ours: string // colour of the moment's team
  theirs: string
  label: string
}

// StatsBomb's pitch, 120 x 80, the team in the moment always attacking left to right. Only the
// players in the moment are drawn, at the event's x and y, as in the mockup.
export function Pitch({ moment, ours, theirs, label }: Props) {
  const placed = moment?.x !== undefined && moment?.y !== undefined
  const x = moment?.x ?? 60
  const y = moment?.y ?? 40
  const shot = moment?.type === 'Shot'
  const goalY = Math.min(Math.max(y, 37), 43)
  const keeper = moment?.players.keeper
  const card = moment ? cardKind(moment) : null
  const word = moment ? caption(moment) : null
  const key = moment ? `${moment.match_id}-${moment.idx}` : 'none'

  return (
    <svg className="field" viewBox="-4 -4 128 88" role="img" aria-label={`${label}: pitch`}>
      <g className="markings">
        <rect x={0} y={0} width={120} height={80} />
        <line x1={60} y1={0} x2={60} y2={80} />
        <circle cx={60} cy={40} r={10} />
        <rect x={0} y={18} width={18} height={44} />
        <rect x={102} y={18} width={18} height={44} />
        <rect x={0} y={30} width={6} height={20} />
        <rect x={114} y={30} width={6} height={20} />
        <rect x={-2} y={36} width={2} height={8} />
        <rect x={120} y={36} width={2} height={8} />
      </g>
      {word && <text key={`c${key}`} className="caption" x={60} y={11} textAnchor="middle">{word}</text>}
      {moment && shot && (
        <Stickman x={117} y={goalY + 4} color={theirs} pose={moment.outcome === 'Saved' ? 'dive' : 'stand'}
          label={keeper ? shortName(keeper) : undefined} labelBelow />
      )}
      {moment && placed && (
        <Stickman x={x} y={y} color={ours} pose={poseFor(moment)} label={shortName(leadPlayer(moment))} />
      )}
      {moment && placed && card && (
        <rect x={x + 2.4} y={y - 15} width={2.6} height={3.6} rx={0.3} fill={card.startsWith('Yellow') ? '#FFD23F' : '#FF6B6B'} />
      )}
      {moment && placed && shot && <BallPath key={key} id={key} from={[x + 1.5, y - 1]} to={shotEnd(moment, y, goalY)} />}
    </svg>
  )
}

function poseFor(m: Moment): Pose {
  if (isGoal(m)) return 'cheer'
  if (m.type === 'Shot') return 'kick'
  return 'stand'
}

function shotEnd(m: Moment, y: number, goalY: number): [number, number] {
  if (m.outcome === 'Goal') return [121, goalY]
  if (m.outcome === 'Saved') return [115.5, goalY - 2]
  if (m.outcome === 'Post') return [120, y < 40 ? 36 : 44]
  return [120, y < 40 ? Math.max(y - 6, 26) : Math.min(y + 6, 54)] // wide, blocked or over
}
