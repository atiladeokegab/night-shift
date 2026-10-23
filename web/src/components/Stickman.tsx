export type Pose = 'stand' | 'kick' | 'dive' | 'bat' | 'bowl' | 'cheer'

interface Props {
  x: number
  y: number // where the feet are
  color: string
  pose?: Pose
  label?: string
  labelBelow?: boolean
}

// A stickman drawn at 1.5x (the mockup's size, readable from the back of a room) around its feet, so
// it stands on event coordinates. Moves with a CSS transition (600ms, docs/design.md "Motion").
// Its name is pulled in from the field's edges so it is never cut off (both fields are 120 wide).
export function Stickman({ x, y, color, pose = 'stand', label, labelBelow = false }: Props) {
  const limbs = POSES[pose]
  const half = (label?.length ?? 0) * 0.85 // about half the name's width at the label's size
  const labelX = Math.min(0, 112 - half - x) + Math.max(0, half + 2 - x)
  return (
    <g className="stickman" style={{ transform: `translate(${x}px, ${y}px)` }}>
      <g transform="scale(1.5)" stroke={color} strokeWidth={0.9} strokeLinecap="round" fill="none">
        <circle cx={limbs.head[0]} cy={limbs.head[1]} r={1.4} fill={color} />
        <path d={limbs.path} />
      </g>
      {label && (
        <text className="name" x={labelX} y={labelBelow ? 5.5 : -15.5} textAnchor="middle">
          {label}
        </text>
      )}
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
