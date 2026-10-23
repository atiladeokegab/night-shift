import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { isDemo, listMatches } from './api'
import { Live } from './components/Live'
import { Picker } from './components/Picker'
import type { Match, Sport } from './types'
import { useReplay } from './useReplay'
import { useSpeech } from './useSpeech'

export default function App() {
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [current, setCurrent] = useState<{ match: Match; speed: number } | null>(null)
  const speech = useSpeech()
  const replay = useReplay(speech.say)

  const load = useCallback(() => {
    listMatches()
      .then((all) => {
        // The design lists football first; the server sorts by file name.
        setMatches([...all].sort((a, b) => (a.sport === b.sport ? 0 : a.sport === 'football' ? -1 : 1)))
        setLoadFailed(false)
      })
      .catch(() => setLoadFailed(true))
  }, [])

  useEffect(load, [load])

  const start = (match: Match, speed: number) => {
    speech.hush()
    setCurrent({ match, speed })
    replay.start(match.match_id, speed)
  }

  // One tap starts the other sport's first match at the same speed; the whole page follows it.
  const firstOf = (sport: Sport) => matches?.find((m) => m.sport === sport)
  const switchSport = (sport: Sport) => {
    const next = firstOf(sport)
    if (next && current) start(next, current.speed)
  }

  const back = () => {
    replay.leave()
    speech.hush()
    setCurrent(null)
  }

  return (
    <div className="page">
      <header className="top">
        <h1>Touchline<span className="dot" aria-hidden /></h1>
        {isDemo && <span className="badge">Demo data</span>}
      </header>
      {current ? (
        <Live
          match={current.match}
          replay={replay.state}
          speech={speech}
          canSwitchTo={(s) => !!firstOf(s)}
          onSwitch={switchSport}
          onRetry={() => start(current.match, current.speed)}
          onReconnect={replay.reconnect}
          onBack={back}
        />
      ) : (
        <Picker
          matches={matches}
          error={loadFailed}
          onRetry={() => {
            setLoadFailed(false)
            setMatches(null)
            load()
          }}
          onStart={start}
        />
      )}
    </div>
  )
}
