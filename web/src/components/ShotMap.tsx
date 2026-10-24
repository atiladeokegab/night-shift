import { useEffect, useState } from 'react'
import { place, zoneName, type Shots } from '../shots'

interface Props {
  name: string
  momentIdx: number // the moment on screen: tonight's shots stop here
  load: (name: string, momentIdx: number) => Promise<Shots | null>
  onClose: () => void
}

// The shot map (#120): the player's shots before tonight as faint dots, tonight's so far bright, made
// versus missed, and the hit rate per zone. Numbers only, no commentator, so it works while off air.
export function ShotMap({ name, momentIdx, load, onClose }: Props) {
  const [shots, setShots] = useState<Shots | null | 'loading' | 'error'>('loading')

  useEffect(() => {
    let live = true // a newer moment or a closed sheet drops this answer
    load(name, momentIdx).then((s) => live && setShots(s), () => live && setShots('error'))
    return () => { live = false }
  }, [name, momentIdx, load])

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  return (
    <div className="scrim" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sheet glass shotmap" role="dialog" aria-modal="true" aria-labelledby="shots-h">
        {/* Close sits in the header: a footer bar would cover the zone table's last rows */}
        <div className="shots-h">
          <h2 id="shots-h">{name}</h2>
          <button className="btn sm" onClick={onClose}>Close</button>
        </div>
        {shots === 'loading' ? (
          <p className="lede"><span className="spin sm" /> Loading shots…</p>
        ) : shots === 'error' ? (
          <p className="err-text" role="alert">Couldn't load the shots. Close and try again.</p>
        ) : shots === null ? (
          <p className="lede">No shot record for {name} in this match.</p>
        ) : (
          <Chart shots={shots} />
        )}
      </div>
    </div>
  )
}

function Chart({ shots }: { shots: Shots }) {
  const ball = shots.sport === 'basketball'
  const k = ball ? 1 : 0.17 // dot sizes in each court's units
  const made = ball ? 'Made' : 'Goal'
  const att = shots.zones.reduce((n, z) => n + z.attempts, 0)
  const hit = shots.zones.reduce((n, z) => n + z.made, 0)
  const tonightMade = shots.tonight.filter((s) => s.made).length
  const pct = (r: number) => `${Math.round(r * 100)}%`
  return (
    <>
      <p className="lede num">
        Before tonight {hit} of {att}{att ? ` (${pct(hit / att)})` : ''} · Tonight {tonightMade} of {shots.tonight.length}
      </p>
      <div className="shots-body">
      <svg className="court" viewBox={ball ? '-255 -55 510 482' : '-2 -4 84 66'} role="img"
        aria-label={`${shots.player}'s shots: ${shots.season.length} before tonight, ${shots.tonight.length} tonight`}>
        {ball ? <Court /> : <Pitch />}
        {shots.season.map((s, i) => {
          const [x, y] = place(shots.sport, s.x, s.y)
          return <circle key={i} className={`season${s.made ? ' made' : ''}`} cx={x} cy={y} r={4 * k} />
        })}
        {shots.tonight.map((s, i) => {
          const [x, y] = place(shots.sport, s.x, s.y)
          return <circle key={`t${i}`} className={`tonight ${s.made ? 'made' : 'miss'}`} cx={x} cy={y} r={8 * k} strokeWidth={3 * k} />
        })}
      </svg>
      <div>
      <p className="legend">
        <span><i className="dot season" />Before tonight</span>
        <span><i className="dot made" />{made}</span>
        <span><i className="dot miss" />{ball ? 'Missed' : 'No goal'}</span>
      </p>
      <table className="zones">
        <caption className="label">Hit rate by zone</caption>
        <tbody>
          {[...shots.zones].sort((a, b) => b.attempts - a.attempts).map((z) => (
            <tr key={z.zone}>
              <th scope="row">{zoneName(z.zone)}</th>
              <td className="num">{z.made} of {z.attempts}</td>
              <td className="num rate"><span style={{ width: pct(z.rate) }} />{pct(z.rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      </div>
    </>
  )
}

// An NBA half-court in tenths of a foot, hoop at the origin, baseline at y = -47.5.
function Court() {
  return (
    <g className="marks">
      <rect x={-250} y={-47.5} width={500} height={470} />
      <rect x={-80} y={-47.5} width={160} height={190} />
      <circle cx={0} cy={142.5} r={60} />
      <path d="M -40 0 A 40 40 0 0 0 40 0" />
      <path d="M -220 -47.5 L -220 89.5 A 237.5 237.5 0 0 0 220 89.5 L 220 -47.5" />
      <path d="M -60 422.5 A 60 60 0 0 1 60 422.5" />
      <line x1={-30} y1={-7.5} x2={30} y2={-7.5} />
      <circle cx={0} cy={0} r={7.5} />
    </g>
  )
}

// A StatsBomb attacking half (120x80 turned by place()): goal at the top, halfway line at the bottom.
function Pitch() {
  return (
    <g className="marks thin">
      <rect x={0} y={0} width={80} height={60} />
      <rect x={18} y={0} width={44} height={18} />
      <rect x={30} y={0} width={20} height={6} />
      <rect x={36} y={-2} width={8} height={2} />
      <circle cx={40} cy={12} r={0.4} />
      <path d="M 32 18 A 10 10 0 0 0 48 18" />
      <path d="M 30 60 A 10 10 0 0 1 50 60" />
    </g>
  )
}
