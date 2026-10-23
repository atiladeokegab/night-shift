export type Pose = 'stand' | 'kick' | 'dive' | 'bat' | 'bowl' | 'cheer'

interface Props {
  x: number
  y: number // where the feet are
  color: string
  pose?: Pose
  faded?: boolean
}

// A stickman 9 units tall, drawn around its feet so it can be placed on event coordinates.
// Moves with a CSS transition, so a new position animates from the old one.
export function Stickman({ x, y, color, pose = 'stand', faded = false }: Props) {
  const limbs = POSES[pose]
  return (
    <g
      className="stickman"
      style={{ transform: `translate(${x}px, ${y}px)` }}
      stroke={color}
      strokeWidth={0.9}
      strokeLinecap="round"
      fill="none"
      opacity={faded ? 0.35 : 1}
    >
      <circle cx={limbs.head[0]} cy={limbs.head[1]} r={1.4} fill={color} />
      <path d={limbs.path} />
    </g>
  )
}

// Each pose: head centre and one path for body, arms and legs, relative to the feet at 0,0.
const POSES: Record<Pose, { head: [number, number]; path: string }> = {
  stand: { head: [0, -8], path: 'M0 -6.6 V-3 M-2 -5 L0 -5.6 L2 -5 M0 -3 L-1.4 0 M0 -3 L1.4 0' },
  kick: { head: [-0.4, -8], path: 'M-0.4 -6.6 L0 -3 M-2.6 -4.6 L-0.2 -5.6 L2 -6.4 M0 -3 L-1.4 0 M0 -3 L3 -2' },
  dive: { head: [-5, -3], path: 'M-3.8 -2.6 L1 -1.6 M-6.4 -4.4 L-4 -2.6 M1 -1.6 L3.6 -0.6 M1 -1.6 L3 0' },
  bat: { head: [0, -8], path: 'M0 -6.6 V-3 M0 -5.4 L1.8 -4.4 L3.2 -7.4 M0 -3 L-1.4 0 M0 -3 L1.4 0' },
  bowl: { head: [0.4, -8], path: 'M0.4 -6.6 L0 -3 M0.2 -5.6 L-0.6 -9.4 M0.2 -5.6 L2.6 -4 M0 -3 L-2 0 M0 -3 L1.8 -0.6' },
  cheer: { head: [0, -8], path: 'M0 -6.6 V-3 M0 -5.6 L-2 -8.6 M0 -5.6 L2 -8.6 M0 -3 L-1.6 0 M0 -3 L1.6 0' },
}
