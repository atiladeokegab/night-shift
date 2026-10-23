interface Props {
  id: string // unique per moment, so each new moment draws its path again
  from: [number, number]
  to: [number, number]
}

// The moment's ball path: a dashed amber line that draws in over 400ms (docs/design.md "Motion").
// The dashes are fixed; a mask with a growing solid stroke reveals them from the start point.
export function BallPath({ id, from, to }: Props) {
  const d = `M${from[0]} ${from[1]} L${to[0]} ${to[1]}`
  return (
    <g>
      <mask id={`reveal-${id}`} maskUnits="userSpaceOnUse" x={-20} y={-20} width={200} height={200}>
        <path className="reveal" d={d} pathLength={1} stroke="#fff" strokeWidth={3} fill="none" />
      </mask>
      <path className="ball-path" d={d} mask={`url(#reveal-${id})`} />
      <circle className="ball" cx={to[0]} cy={to[1]} r={1.1} />
    </g>
  )
}
