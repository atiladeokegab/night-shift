import { useEffect, useRef, useState } from 'react'
import './App.css'
import { isDemo, listMatches, startReplay } from './api'
import { Ground } from './components/Ground'
import { Pitch } from './components/Pitch'
import { ScoreBar } from './components/ScoreBar'
import type { Line, Match, Moment, Sport } from './types'
import { useSpeech } from './useSpeech'

const COLORS = { home: '#ff6b5e', away: '#5eb8ff' }
const SPORTS: Sport[] = ['football', 'cricket']
const SPEEDS = [1, 4, 10]

export default function App() {
  const [matches, setMatches] = useState<Match[]>([])
  const [matchId, setMatchId] = useState<string | null>(null)
  const [speed, setSpeed] = useState(4)
  const [running, setRunning] = useState(false)
  const [moment, setMoment] = useState<Moment | null>(null)
  const [lines, setLines] = useState<Line[]>([])
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const speech = useSpeech()

  // The stream callback reads the latest `say` through a ref, so toggling the voice never restarts a replay.
  const say = useRef(speech.say)
  useEffect(() => {
    say.current = speech.say
  }, [speech.say])

  useEffect(() => {
    listMatches()
      .then((all) => {
        setMatches(all)
        setMatchId(all[0]?.id ?? null)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!running || !matchId) return
    let stop: (() => void) | null = null
    let cancelled = false
    startReplay(
      matchId,
      speed,
      (e) => {
        if (e.type === 'moment') setMoment(e.moment)
        if (e.type === 'line') {
          setLines((prev) => [e.line, ...prev])
          say.current(e.line.text)
        }
        if (e.type === 'end') setEnded(true)
      },
      setError,
    )
      .then((s) => (cancelled ? s() : (stop = s)))
      .catch((e: Error) => setError(e.message))
    return () => {
      cancelled = true
      stop?.()
      window.speechSynthesis?.cancel()
    }
  }, [running, matchId, speed])

  const match = matches.find((m) => m.id === matchId) ?? null
  const sport = match?.sport ?? 'football'
  const ofSport = matches.filter((m) => m.sport === sport)

  // Every change that starts a new replay clears the old one's moment, lines and errors first.
  const clear = () => {
    setMoment(null)
    setLines([])
    setEnded(false)
    setError(null)
  }
  const pickMatch = (id: string) => {
    clear()
    setMatchId(id)
  }

  // One tap: pick the first match of the other sport; a running replay follows to it.
  const switchSport = (next: Sport) => {
    const first = matches.find((m) => m.sport === next)
    if (first) pickMatch(first.id)
  }

  const latest = lines[0]
  const latestMoment = latest && moment?.id === latest.moment_id ? moment : null

  return (
    <div className="page">
      <header className="top">
        <h1>Touchline</h1>
        <nav className="sports" aria-label="Sport">
          {SPORTS.map((s) => (
            <button
              key={s}
              className={s === sport ? 'active' : ''}
              aria-pressed={s === sport}
              disabled={!matches.some((m) => m.sport === s)}
              onClick={() => switchSport(s)}
            >
              {s === 'football' ? 'Football' : 'Cricket'}
            </button>
          ))}
        </nav>
        {isDemo && <span className="badge">Demo data</span>}
      </header>

      {error && <p className="error" role="alert">{error}</p>}
      {!match && !error && <p className="empty">Loading matches…</p>}

      {match && (
        <main>
          <div className="controls">
            <select value={match.id} onChange={(e) => pickMatch(e.target.value)} aria-label="Match">
              {ofSport.map((m) => <option key={m.id} value={m.id}>{m.title}</option>)}
            </select>
            <select
              value={speed}
              onChange={(e) => {
                clear()
                setSpeed(Number(e.target.value))
              }}
              aria-label="Replay speed"
            >
              {SPEEDS.map((s) => <option key={s} value={s}>{s}× speed</option>)}
            </select>
            <button
              className="primary"
              onClick={() => {
                if (!running) clear()
                setRunning(!running)
              }}
            >
              {running ? 'Stop' : 'Start replay'}
            </button>
            {speech.supported && (
              <button onClick={() => speech.setOn(!speech.on)} aria-pressed={speech.on}>
                {speech.on ? 'Voice on' : 'Voice off'}
              </button>
            )}
          </div>

          <ScoreBar match={match} moment={moment} colors={COLORS} />

          <div className="stage">
            {sport === 'football'
              ? <Pitch match={match} moment={moment} colors={COLORS} />
              : <Ground match={match} moment={moment} colors={COLORS} />}
            <div className="subtitle" aria-live="assertive">
              {latest ? (
                <>
                  {latestMoment && <span className="who">{latestMoment.player} · {latestMoment.clock}</span>}
                  <span className="text">{latest.text}</span>
                </>
              ) : (
                <span className="text muted">{running ? 'Waiting for the first moment…' : 'Press Start replay.'}</span>
              )}
            </div>
          </div>

          {ended && <p className="empty">Full time. Pick another moment or switch sport.</p>}

          <ol className="log" aria-label="Commentary so far">
            {lines.map((l) => (
              <li key={l.id}>
                <span className="text">{l.text}</span>
                <span className="latency">{l.latency_ms} ms</span>
              </li>
            ))}
          </ol>
        </main>
      )}
    </div>
  )
}
