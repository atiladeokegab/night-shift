import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import './App.css'
import { listMatches, listVoices, postFix, videoStartAt } from './api'
import { About } from './components/About'
import type { FixPhase } from './components/FixSheet'
import { FixSheet } from './components/FixSheet'
import { submitFix, type Refused } from './fix'
import { embeds } from './player'
import { Live, type VoiceStatus } from './components/Live'
import type { Screen } from './components/Nav'
import { Picker } from './components/Picker'
import { Review } from './components/Review'
import type { VideoState } from './components/VideoStage'
import { VoiceSheet } from './components/VoiceSheet'
import { Wall } from './components/Wall'
import { chipName, defaultVoice, wallOrder } from './teams'
import { SPORTS, type Answer, type Line, type Match, type Moment, type Sport, type Voice } from './types'
import { QuietSpell, WHERE } from './quiet'
import { askKey, isRepeat } from './ask'
import { airAnswer, bigSoon, isBig, isDecisive, type Caption } from './turns'
import { onScreen, useReplay } from './useReplay'
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
  const [fixing, setFixing] = useState<{ line: Line; phase: FixPhase; refused?: Refused } | null>(null)
  const [voiceSheet, setVoiceSheet] = useState(false)
  const [toast, setToast] = useState('')
  // #131: a viewer's question, then its answer, takes the caption from the lines while it is on
  const [asking, setAsking] = useState<Caption | null>(null)
  const asked = useRef(0) // only the newest question may change the caption
  const inFlight = useRef<string | null>(null) // the question being asked, by askKey
  const [interrupted, setInterrupted] = useState<string[]>([]) // answers a decisive moment cut off
  const [paused, setPaused] = useState(false)
  const [describeQuiet, setDescribeQuiet] = useState(true) // #186: on by default
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
  // A big moment may cut in on the other commentator (#131). Its moment is presented in the same render
  // as the line; a layout effect runs before useReplay's speaking effect, so `presented` already has it.
  const presented = useRef<Moment[]>([])
  const sayLine = useCallback(
    (line: Line) => {
      const m = presented.current.find((x) => x.idx === line.moment_idx)
      speech.say(line, voiceNow.current, isBig(m), isDecisive(m))
    },
    [speech],
  )
  const replay = useReplay(sayLine, speech.hush)
  const ahead = useRef(replay.state) // #139: the moments still to come, for an answer waiting for a gap
  useLayoutEffect(() => {
    presented.current = replay.state.moments
    ahead.current = replay.state
  }, [replay.state])
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
        setMatches(wallOrder(all))
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
  const start = (match: Match, speed: number, switching = false, fromHistory = false, startIdx?: number) => {
    if (!fromHistory) {
      const entry = { screen: 'live', match: match.match_id, speed }
      if (screen === 'live') window.history.replaceState(entry, '')
      else window.history.pushState(entry, '')
    }
    session.current++
    speech.hush()
    setAsking(null)
    setPaused(false)
    setFixing(null)
    setVoiceSheet(false)
    setVideo(embeds(match) ? 'loading' : 'unavailable')
    setCurrent((prev) => ({ match, speed, key: (prev?.key ?? 0) + 1, switching }))
    setScreen('live')
    // A match with a highlights video holds its commentary for the player (A-6.4@2).
    replay.start(match.match_id, speed, !!match.youtube_id, match.video_start, startIdx)
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
    setAsking(null)
    setPaused(false)
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
      if (window.location.hash === '#review') return // the #review link (#171): onHash below opens Review
      const to = e.state as { screen?: Screen; match?: string; speed?: number } | null
      const m = to?.screen === 'live' ? matches?.find((x) => x.match_id === to.match) : undefined
      if (m) start(m, to?.speed ?? 1, false, true)
      else go(to?.screen && to.screen !== 'live' ? to.screen : 'wall', true)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  })

  // #188: ?match=<id>&at=<idx> opens that match at that moment, as its jump pill does (a film take).
  const opened = useRef(false)
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    const m = matches?.find((x) => x.match_id === q.get('match'))
    const at = Number(q.get('at') ?? NaN)
    if (!m || !Number.isInteger(at) || opened.current) return
    opened.current = true
    videoStartAt(m.match_id, at).then((s) =>
      start({ ...m, video_start: s ?? m.video_start }, m.youtube_id ? 1 : 4, false, false, at),
    )
  })

  // #171: the Proof card links to #review, so it opens the Review screen without a route through Live.
  // The hash is replaced by Review's own entry, so the link works again next time.
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash !== '#review') return
      window.history.replaceState({ screen: 'review' }, '', window.location.pathname + window.location.search)
      go('review', true)
    }
    onHash()
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
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
      // A 503 or 422 stores nothing (CONTRACT.md), so the sheet stays open with the text to send again.
      (refused) => setFixing((f) => (mine(f) ? { line, phase: 'error', refused } : f)),
    )
  }

  // #117: an off-air answer is shown, never spoken. #131: the stage shows the question, then the answer
  // while it is spoken. #139: the analyst answers at a gap, never with a big moment due in the next 3 s.
  // A decisive moment may cut an answer off: the Lines card marks it, with "Hear it again".
  // A new ask (no `again`) is sent once: the quiet-spell ask and a press at the same moment are one row.
  const askCommentator = async (question: string, momentIdx: number, viewer = true, again?: () => Promise<Answer>) => {
    if (!again && isRepeat(replay.state.answers, inFlight.current, question, momentIdx)) return
    const key = again ? null : (inFlight.current = askKey(question, momentIdx))
    const sent = session.current
    const mine = ++asked.current
    try {
      await airAnswer(
        question,
        again ?? (() => replay.ask(question, momentIdx)),
        (answer, started) =>
          answer.off_air
            ? null
            : (speech
                .sayAnswer(answer, voiceNow.current, started, () => bigSoon(ahead.current.queuedMoments, ahead.current.now))
                ?.then((cut) => {
                  if (cut && session.current === sent) setInterrupted((ids) => [...ids, answer.line_id])
                }) ?? null),
        setAsking,
        () => session.current === sent && asked.current === mine,
        undefined,
        viewer ? undefined : '',
      )
    } finally {
      if (key && inFlight.current === key) inFlight.current = null
    }
  }
  const hearAgain = (answer: Answer) => {
    setInterrupted((ids) => ids.filter((id) => id !== answer.line_id))
    void askCommentator(answer.question, answer.moment_idx, true, async () => answer)
  }

  // The stage's caption (#132's contract): the question or answer while one is on, else the line on
  // screen (its fix once fixed), with its speaker for the name chip.
  const shown = onScreen(replay.state)
  const latest = shown.lines.find((l) => !replay.state.late.includes(l.line_id))
  const fixed = latest && replay.state.fixes[latest.line_id]
  const caption: Caption | null =
    asking ?? (latest ? { kind: 'line', text: fixed ? fixed.corrected_text : latest.text, speaker: latest.speaker ?? 'lead' } : null)

  // #186: 15 s of play with no new line, and the page asks "Where are we?" itself, once per quiet spell.
  const quiet = useRef(new QuietSpell())
  useEffect(() => quiet.current.said(Date.now()), [latest?.line_id, current?.key])
  const onAir = shown.moments.at(-1)
  const playing = screen === 'live' && replay.state.phase === 'live' && video !== 'loading' && !paused && !asking &&
    !(replay.state.ended && replay.state.queuedMoments.length === 0)
  const tick = useRef(() => {})
  useEffect(() => {
    tick.current = () => {
      if (quiet.current.due(Date.now(), playing && describeQuiet && !!onAir) && onAir) void askCommentator(WHERE, onAir.idx, false)
    }
  })
  useEffect(() => {
    const id = window.setInterval(() => tick.current(), 1000)
    return () => window.clearInterval(id)
  }, [])
  // Pausing stops the voice at once; the paused player's clock holds the commentary (A-6.4@2).
  const stage = {
    caption,
    paused,
    onPause: () => {
      speech.hush()
      setPaused(true)
    },
    onPlay: () => setPaused(false),
    volume: speech.volume,
    muted: speech.muted,
    onVolume: speech.setVolume,
  }

  const sports = SPORTS.filter((s) => matches?.some((m) => m.sport === s))
  const voiceUsable = speech.available || voices.some((v) => !v.browser)
  const voiceStatus: VoiceStatus = !voiceUsable ? 'unavailable' : speech.on ? 'on' : 'off'
  // Who reads the analyst's lines: the server's voice for the sport, or the browser's own speech.
  const analyst = voice?.browser ? chipName(voice) : chipName(voices.find((v) => sport && v.analyst_for?.includes(sport)) ?? null)

  return (
    <>
      {screen === 'live' && current ? (
        <Live
          {...stage}
          match={current.match}
          replay={replay.state}
          replayKey={current.key}
          switching={current.switching}
          sports={sports}
          voice={{ status: voiceStatus, chip: chipName(voice), speaking: speech.speaking, analyst, fellBack: speech.fellBack }}
          video={video}
          onVideo={onVideo}
          onClock={replay.setClock}
          onSport={switchSport}
          onNext={(matches?.length ?? 0) > 1 ? next : null}
          onVoiceSheet={() => setVoiceSheet(true)}
          onFix={(line) => setFixing({ line, phase: 'edit' })}
          onAsk={askCommentator}
          onLook={replay.look}
          mic={{ airing: speech.airing, duck: speech.hush }}
          interrupted={interrupted}
          onHear={hearAgain}
          onShots={replay.shots}
          onPlayers={replay.players}
          onProfile={replay.profile}
          onRetry={() => start(current.match, current.speed)}
          onReconnect={replay.reconnect}
          onGo={go}
        />
      ) : screen === 'about' ? (
        <About onGo={go} />
      ) : screen === 'review' ? (
        <Review onGo={go} />
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
          // #163: the same stage, with the video and the commentary both starting just before the peak
          onJump={(m) => start({ ...m, video_start: m.peak_video_start }, m.youtube_id ? 1 : 4, false, false, m.peak_idx)}
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
        <FixSheet key={fixing.line.line_id} line={fixing.line} phase={fixing.phase} refused={fixing.refused} onSend={sendFix}
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
          describeQuiet={describeQuiet}
          onDescribeQuiet={setDescribeQuiet}
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
