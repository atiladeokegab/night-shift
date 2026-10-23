import { cardColor, isGoal } from '../moment'
import type { Moment } from '../types'
import { Stickman, type Pose } from './Stickman'

interface Props {
  moment: Moment | null
  attack: string // colour of the moment's team
  defend: string
  label: string
}

// StatsBomb coordinates: 120 x 80, the team in the moment always attacking left to right.
// Background players stand in a 4-3-3 each; the player in the moment moves to the event spot.
const ATTACK: [number, number][] = [
  [8, 40], [30, 12], [26, 30], [26, 50], [30, 68], [50, 24], [46, 40], [50, 56], [74, 16], [78, 40], [74, 64],
]
// Mirrored, and outfielders shifted down so the two midfields don't stand on the same spots.
const DEFEND: [number, number][] = ATTACK.map(([x, y], i) => [120 - x, i === 0 ? y : y + 6])

export function Pitch({ moment, attack, defend, label }: Props) {
  const placed = moment?.x !== undefined && moment?.y !== undefined
  const x = moment?.x ?? 60
  const y = moment?.y ?? 40
  const ball = ballSpot(moment, x, y)
  const saved = moment?.type === 'Shot' && moment.outcome === 'Saved'
  const card = moment ? cardColor(moment) : null

  return (
    <svg className="field" viewBox="-4 -4 128 88" role="img" aria-label={`${label}: pitch`}>
      <g className="markings" fill="none">
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
      {ATTACK.map(([px, py], i) => <Stickman key={`a${i}`} x={px} y={py} color={attack} faded />)}
      {DEFEND.map(([px, py], i) => <Stickman key={`d${i}`} x={px} y={py} color={defend} faded />)}
      {saved && <Stickman x={116} y={ball[1] + 3} color={defend} pose="dive" />}
      {moment && placed && <Stickman x={x} y={y} color={attack} pose={poseFor(moment)} />}
      {card && placed && <rect x={x + 2} y={y - 12} width={2.4} height={3.4} rx={0.3} fill={card} />}
      <circle className="ball" r={1.1} style={{ transform: `translate(${ball[0]}px, ${ball[1]}px)` }} />
    </svg>
  )
}

function poseFor(m: Moment): Pose {
  if (isGoal(m)) return 'cheer'
  if (m.type === 'Shot') return 'kick'
  return 'stand'
}

function ballSpot(moment: Moment | null, x: number, y: number): [number, number] {
  if (!moment) return [60, 40]
  const gy = Math.min(Math.max(y, 37), 43)
  if (isGoal(moment)) return [121, gy]
  if (moment.type === 'Shot') return moment.outcome === 'Saved' ? [115, gy] : [118, Math.min(Math.max(y, 32), 48)]
  return [x + 2, y - 0.5]
}
