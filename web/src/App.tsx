import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { isDemo, listMatches, listVoices } from './api'
import { Live } from './components/Live'
import { Picker } from './components/Picker'
import type { Line, Match, Sport, Voice } from './types'
import { useReplay } from './useReplay'
import { useSpeech } from './useSpeech'

export default function App() {
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [current, setCurrent] = useState<{ match: Match; speed: number; key: number } | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  // A-6.3@1: a voice picked for a sport sticks to that sport; otherwise its default_for voice.
  const [picked, setPicked] = useState<Partial<Record<Sport, string>>>({})
  const speech = useSpeech()

  const sport = current?.match.sport
  const voice = sport ? (voices.find((v) => v.id === picked[sport]) ?? voices.find((v) => v.default_for === sport) ?? voices[0] ?? null) : null

  // Lines arrive on the stream; each is read in the voice chosen when it lands, so a change applies
  // from the next line without restarting the replay.
  const voiceNow = useRef(voice)
  useEffect(() => {
    voiceNow.current = voice
  }, [voice])
  const sayLine = useCallback((line: Line) => speech.say(line, voiceNow.current), [speech])
  const replay = useReplay(sayLine, speech.hush)

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
  useEffect(() => {
    listVoices().then(setVoices)
  }, [])

  const start = (match: Match, speed: number) => {
    speech.hush()
    setCurrent((prev) => ({ match, speed, key: (prev?.key ?? 0) + 1 }))
    // A match with a highlights video holds its commentary for the player (A-6.4@2).
    replay.start(match.match_id, speed, !!match.youtube_id)
  }

  // One tap starts the other sport's first match at the same speed; the whole page follows it.
  const firstOf = (s: Sport) => matches?.find((m) => m.sport === s)
  const switchSport = (s: Sport) => {
    const next = firstOf(s)
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
          replayKey={current.key}
          speech={speech}
          voices={voices}
          voiceId={voice?.id ?? null}
          onVoice={(id) => setPicked((p) => ({ ...p, [current.match.sport]: id }))}
          onClock={replay.setClock}
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
