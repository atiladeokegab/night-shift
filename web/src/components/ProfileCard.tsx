import { useEffect, useState } from 'react'
import { answerFor, libraryLine, PHASES, recordLine, sampleNote, tonightLine, type Asked, type Profile } from '../follow'

interface Props {
  name: string
  replayKey: number
  momentIdx: number // the moment on screen: tonight stops here
  load: (name: string, momentIdx: number) => Promise<Profile | null>
  onShots: ((name: string) => void) | null // basketball and football: open the shot map for them
  onUnfollow: () => void
}

// The followed player's card (#140): photo-free, the record before tonight and tonight so far, updating
// as the replay plays. Cricket adds the phase chart, F1 the places by lap; the others open the shot map.
export function ProfileCard({ name, replayKey, momentIdx, load, onShots, onUnfollow }: Props) {
  const [got, setGot] = useState<Asked<Profile | null> | null>(null)
  const p = answerFor(got, replayKey, name, momentIdx)

  useEffect(() => {
    let live = true // a newer moment, player or replay drops this answer
    const done = (value: Profile | null | 'error') => live && setGot({ replay: replayKey, name, momentIdx, value })
    load(name, momentIdx).then(done, () => done('error'))
    return () => { live = false }
  }, [name, replayKey, momentIdx, load])

  const note = p && typeof p === 'object' ? sampleNote(p) : null
  return (
    <section className="panel glass profile" aria-label={`Following ${name}`}>
      <div className="panel-h">
        <div>
          <span className="label">Following</span>
          <h2>{name}</h2>
          {p && typeof p === 'object' && p.team && <span className="hint">{p.team}</span>}
        </div>
        <button className="btn sm" onClick={onUnfollow}>Unfollow</button>
      </div>
      {p === 'loading' ? (
        <p className="hint"><span className="spin sm" /> Loading…</p>
      ) : p === 'error' ? (
        <p className="err-text" role="alert">Couldn't load the profile.</p>
      ) : p === null ? (
        <p className="hint">No profile for {name} in this match.</p>
      ) : (
        <>
          <dl className="stat-lines">
            {p.before && <><dt className="label">Before tonight</dt><dd className="num">{recordLine(p)}</dd></>}
            <dt className="label">Tonight</dt><dd className="num">{tonightLine(p)}</dd>
            {p.library?.length ? <><dt className="label">Also in our library</dt>{p.library.map((m) => <dd key={m.match_id}>{libraryLine(m)}</dd>)}</> : null}
          </dl>
          {note && <p className="hint">{note}</p>}
          {p.sport === 'cricket' && <Phases p={p} />}
          {p.sport === 'f1' && <Laps laps={p.tonight.laps ?? []} />}
          {onShots && <button className="btn sm" onClick={() => onShots(name)}>Shot map · {name}</button>}
        </>
      )}
    </section>
  )
}

// Batting by phase: runs off balls before tonight and tonight, the bar the strike rate (200 fills it).
function Phases({ p }: { p: Profile }) {
  const sr = (runs: number, balls: number) => (balls ? Math.round((runs / balls) * 100) : 0)
  const nb = (s: string) => s.replaceAll(' ', '\u00a0') // a narrow card wraps at the ' · ', never inside '0 off 1'
  return (
    <table className="zones">
      <caption className="label">Batting by phase</caption>
      <tbody>
        {PHASES.map((ph) => {
          const b = p.before?.batting?.[ph] ?? { balls: 0, runs: 0 }
          const t = p.tonight.batting![ph]
          const rate = sr(b.runs + t.runs, b.balls + t.balls)
          return (
            <tr key={ph}>
              <th scope="row">{ph[0].toUpperCase() + ph.slice(1)}</th>
              <td className="num">{nb(`${b.runs} off ${b.balls}`)}{t.balls ? ` · ${nb(`${t.runs} off ${t.balls} tonight`)}` : ''}</td>
              <td className="num rate"><span style={{ width: `${Math.min(100, rate / 2)}%` }} />SR {rate}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// Places by lap while in the top five (the feed carries only the top five), P1 at the top.
function Laps({ laps }: { laps: { lap: number; pos: number }[] }) {
  if (!laps.length) return <p className="hint">Not in the top five yet: places show from there.</p>
  const last = Math.max(...laps.map((l) => l.lap))
  const x = (lap: number) => (lap / last) * 300
  const y = (pos: number) => (pos - 1) * 20 + 10
  return (
    <svg className="laps" viewBox="-24 0 334 116" role="img" aria-label={`Places by lap: ${laps.map((l) => `P${l.pos} on lap ${l.lap}`).join(', ')}`}>
      {[1, 2, 3, 4, 5].map((pos) => (
        <g key={pos}>
          <line x1={0} x2={300} y1={y(pos)} y2={y(pos)} className="grid" />
          <text x={-6} y={y(pos) + 4} textAnchor="end">P{pos}</text>
        </g>
      ))}
      <text x={300} y={112} textAnchor="end">Lap {last}</text>
      <polyline points={laps.map((l) => `${x(l.lap)},${y(l.pos)}`).join(' ')} />
      {laps.map((l) => <circle key={l.lap} cx={x(l.lap)} cy={y(l.pos)} r={4} />)}
    </svg>
  )
}
