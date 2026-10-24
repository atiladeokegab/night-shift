import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import { listMatches, listVoices, postFix } from './api'
import { About } from './components/About'
import type { FixPhase } from './components/FixSheet'
import { FixSheet } from './components/FixSheet'
import { submitFix } from './fix'
import { embeds } from './player'
import { Live, type VoiceStatus } from './components/Live'
import type { Screen } from './components/Nav'
import { Picker } from './components/Picker'
import type { VideoState } from './components/VideoStage'
import { VoiceSheet } from './components/VoiceSheet'
import { Wall } from './components/Wall'
import { chipName, defaultVoice } from './teams'
import { SPORTS, type Line, type Match, type Sport, type Voice } from './types'
import { useReplay } from './useReplay'
import { useSpeech } from './useSpeech'
import { viewOf } from './view'

const TOAST_MS = 2400

export default function App() {
  const [screen, setScreen] = useState<Screen>('wall')
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [current, setCurrent] = useState<{ match: Match; speed: number; key: number; switching: boolean } | null>(null)
  const [voices, setVoices] = useState<Voice[]>([])
  // A-6.3@1: a voice picked for a sport sticks to that sport; otherwise its default_for voice.
  const [picked, setPicked] = useState<Partial<Record<Sport, string>>>({})
  const [video, setVideo] = useState<VideoState>('loading')
  const [fixing, setFixing] = useState<{ line: Line; phase: FixPhase } | null>(null)
  const [voiceSheet, setVoiceSheet] = useState(false)
  const [toast, setToast] = useState('')
  const speech = useSpeech()

  const chosen = useCallback(
    (sport: Sport) => voices.find((v) => v.id === picked[sport]) ?? defaultVoice(voices, sport),
    [voices, picked],
  )
  const sport = current?.match.sport
  const voice = sport ? chosen(sport) : null

  // Lines arrive on the stream; each is read in the voice chosen when it is presented, so a change
  // applies from the next line without restarting the replay.
  const voiceNow = useRef(voice)
  useEffect(() => {
    voiceNow.current = voice
  }, [voice])
  const sayLine = useCallback((line: Line) => speech.say(line, voiceNow.current), [speech])
  const replay = useReplay(sayLine, speech.hush)
  const { unGate } = replay
  // A video that can't play here for good says so, and the commentary goes on on the replay's clock.
  const onVideo = useCallback(
    (state: VideoState) => {
      setVideo(state)
      if (state === 'unavailable') unGate()
    },
    [unGate],
  )
  // Bumped on every start and leave: an answer from an older replay (a slow fix POST) is ignored.
  const session = useRef(0)

  const load = useCallback(() => {
    listMatches()
      .then((all) => {
        // The design lists football first; the server sorts by file name.
        setMatches([...all].sort((a, b) => SPORTS.indexOf(a.sport) - SPORTS.indexOf(b.sport)))
        setLoadFailed(false)
      })
      .catch(() => setLoadFailed(true))
  }, [])

  useEffect(load, [load])
  // A new screen or match opens at its top, not at the scroll the wall was left at.
  const view = viewOf(screen, current?.key)
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [view])
  useEffect(() => {
    listVoices().then(setVoices)
  }, [])

  const say = (message: string) => {
    setToast(message)
    window.setTimeout(() => setToast((t) => (t === message ? '' : t)), TOAST_MS)
  }

  // A-6.5: each screen is a browser history entry, so Back from a match returns to the wall.
  // A match opened from another screen pushes one; a switch on the stage replaces it.
  const start = (match: Match, speed: number, switching = false, fromHistory = false) => {
    if (!fromHistory) {
      const entry = { screen: 'live', match: match.match_id, speed }
      if (screen === 'live') window.history.replaceState(entry, '')
      else window.history.pushState(entry, '')
    }
    session.current++
    speech.hush()
    setFixing(null)
    setVoiceSheet(false)
    setVideo(embeds(match) ? 'loading' : 'unavailable')
    setCurrent((prev) => ({ match, speed, key: (prev?.key ?? 0) + 1, switching }))
    setScreen('live')
    // A match with a highlights video holds its commentary for the player (A-6.4@2).
    replay.start(match.match_id, speed, !!match.youtube_id, match.video_start)
  }

  // One tap starts the other sport's first match at the same speed; the whole page follows it.
  const firstOf = (s: Sport) => matches?.find((m) => m.sport === s)
  const switchSport = (s: Sport) => {
    const next = firstOf(s)
    if (next && current) start(next, current.speed, true)
  }

  // A-6.5: one tap from the stage opens the wall's next match; the old one's commentary stops at once
  // (start() hushes the voice, and replay.start() drops every event from the replaced run).
  const next = () => {
    if (!matches?.length || !current) return
    const i = matches.findIndex((m) => m.match_id === current.match.match_id)
    const m = matches[(i + 1) % matches.length]
    start(m, m.youtube_id ? 1 : current.speed)
  }

  const go = (to: Screen, fromHistory = false) => {
    if (to === 'live') {
      if (current) setScreen('live')
      else if (matches?.[0]) start(matches[0], matches[0].youtube_id ? 1 : 4)
      return
    }
    session.current++
    replay.leave()
    speech.hush()
    setCurrent(null)
    setFixing(null)
    setVoiceSheet(false)
    setScreen(to)
    if (!fromHistory && to !== screen) window.history.pushState({ screen: to }, '')
  }

  useEffect(() => window.history.replaceState({ screen: 'wall' }, ''), [])
  // Re-bound every render so Back and Forward see the current matches and screen; leaving goes
  // through go(), which stops the replay and hushes the voice.
  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      const to = e.state as { screen?: Screen; match?: string; speed?: number } | null
      const m = to?.screen === 'live' ? matches?.find((x) => x.match_id === to.match) : undefined
      if (m) start(m, to?.speed ?? 1, false, true)
      else go(to?.screen && to.screen !== 'live' ? to.screen : 'wall', true)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  })

  const sendFix = async (text: string, reason: string) => {
    if (!fixing) return
    const line = fixing.line
    const sent = session.current
    const mine = (f: { line: Line } | null) => f?.line.line_id === line.line_id
    setFixing({ line, phase: 'sending' })
    await submitFix(
      () => postFix(line.line_id, text, reason),
      () => session.current === sent,
      (fix) => {
        replay.markFixed(fix)
        setFixing((f) => (mine(f) ? null : f))
        say('Fix sent. Kept beside the original.')
      },
      // A 503 stores nothing (CONTRACT.md), so the sheet stays open with the text to send again.
      () => setFixing((f) => (mine(f) ? { line, phase: 'error' } : f)),
    )
  }

  const sports = SPORTS.filter((s) => matches?.some((m) => m.sport === s))
  const voiceUsable = speech.available || voices.some((v) => !v.browser)
  const voiceStatus: VoiceStatus = !voiceUsable ? 'unavailable' : speech.on ? 'on' : 'off'

  return (
    <>
      {screen === 'live' && current ? (
        <Live
          match={current.match}
          replay={replay.state}
          replayKey={current.key}
          switching={current.switching}
          sports={sports}
          voice={{ status: voiceStatus, chip: chipName(voice), speaking: speech.speaking }}
          video={video}
          onVideo={onVideo}
          onClock={replay.setClock}
          onSport={switchSport}
          onNext={(matches?.length ?? 0) > 1 ? next : null}
          onVoiceSheet={() => setVoiceSheet(true)}
          onFix={(line) => setFixing({ line, phase: 'edit' })}
          onRetry={() => start(current.match, current.speed)}
          onReconnect={replay.reconnect}
          onGo={go}
        />
      ) : screen === 'about' ? (
        <About onGo={go} />
      ) : screen === 'wall' ? (
        <Wall
          matches={matches}
          error={loadFailed}
          onRetry={() => {
            setLoadFailed(false)
            setMatches(null)
            load()
          }}
          onOpen={(m) => start(m, m.youtube_id ? 1 : 4)}
          onGo={go}
        />
      ) : (
        <Picker
          matches={matches}
          error={loadFailed}
          voices={voices}
          onRetry={() => {
            setLoadFailed(false)
            setMatches(null)
            load()
          }}
          onStart={(m, speed) => start(m, speed)}
          onGo={go}
        />
      )}
      {fixing && (
        <FixSheet key={fixing.line.line_id} line={fixing.line} phase={fixing.phase} onSend={sendFix}
          onCancel={() => setFixing(null)} />
      )}
      {voiceSheet && (
        <VoiceSheet
          sports={sports}
          voices={voices}
          chosen={chosen}
          available={voiceUsable}
          on={speech.on}
          onToggle={speech.setOn}
          onPick={(s, v) => {
            setPicked((p) => ({ ...p, [s]: v.id }))
            say(`${chipName(v)} from the next line.`)
          }}
          onClose={() => setVoiceSheet(false)}
        />
      )}
      {toast && <div className="toast glass" role="status">{toast}</div>}
    </>
  )
}
