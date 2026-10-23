import { useState } from 'react'
import { CARD_COPY } from '../teams'
import type { Match } from '../types'

const SPEEDS: [number, string][] = [[1, 'Real time'], [4, '4x'], [16, '16x']]

interface Props {
  matches: Match[] | null // null while loading
  error: boolean
  onRetry: () => void
  onStart: (match: Match, speed: number) => void
}

// The match picker (docs/design.md "Screens"): one card per match, a speed choice, "Start replay".
export function Picker({ matches, error, onRetry, onStart }: Props) {
  return (
    <main className="picker">
      <p className="tagline">A live AI commentator for matches nobody calls.</p>
      <h2>Pick a match</h2>
      {error ? (
        <div className="state">
          <p>Couldn't load matches. Is the server running?</p>
          <button onClick={onRetry}>Try again</button>
        </div>
      ) : matches === null ? (
        <>
          <div className="cards" aria-hidden>
            <div className="card ghost" />
            <div className="card ghost" />
          </div>
          <p className="state">Loading matches…</p>
        </>
      ) : matches.length === 0 ? (
        <p className="state">No matches yet. Load the demo data, then refresh.</p>
      ) : (
        <div className="cards">
          {matches.map((m) => <Card key={m.match_id} match={m} onStart={onStart} />)}
        </div>
      )}
      <footer>Match data: StatsBomb open data and Cricsheet. Commentary is AI-generated.</footer>
    </main>
  )
}

function Card({ match, onStart }: { match: Match; onStart: Props['onStart'] }) {
  const [speed, setSpeed] = useState(4)
  const copy = CARD_COPY[match.match_id]
  return (
    <section className="card">
      <span className="label">{match.sport === 'football' ? 'Football' : 'Cricket'}</span>
      <h3>{copy?.title ?? match.title?.split(',')[0] ?? match.match_id}</h3>
      {(copy?.detail ?? match.title?.split(',').slice(1).join(',').trim()) && (
        <p className="detail">{copy?.detail ?? match.title?.split(',').slice(1).join(',').trim()}</p>
      )}
      {copy && <p className="result">{copy.result}</p>}
      <div className="speeds" role="group" aria-label="Replay speed">
        {SPEEDS.map(([value, name]) => (
          <button key={value} className={value === speed ? 'on' : ''} aria-pressed={value === speed} onClick={() => setSpeed(value)}>
            {name}
          </button>
        ))}
      </div>
      <button className="primary" onClick={() => onStart(match, speed)}>Start replay</button>
    </section>
  )
}
