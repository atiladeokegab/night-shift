import { useCallback, useEffect, useReducer, useRef } from 'react'
import { askCommentator, createReplay, followReplay, type StreamStatus } from './api'
import { release, replayClock } from './gate'
import type { Answer, Fix, Line, Moment, Stats } from './types'

export interface ReplayState {
  phase: 'idle' | 'starting' | 'live' | 'failed'
  stream: StreamStatus
  gated: boolean // the match has a video: items wait for the player's clock (A-6.4@2)
  now: number // where the picture is, in video seconds (gated only)
  duration: number // the video's length in seconds, once the player knows it
  moments: Moment[] // presented, in order
  lines: Line[] // presented, newest first
  late: string[] // line_ids released after the picture had moved past them: logged, never spoken
  queuedMoments: Moment[] // received ahead of the picture
  queuedLines: Line[]
  ended: boolean
  error: string | null // a server `error` event: the commentator failed mid-replay
  stats: Stats | null // the latest `stats` event; store-wide, so it outlives a single replay
  fixes: Record<string, Fix> // by line_id: from the `fixed` event or the fix request's answer
  answers: Answer[] // viewers' questions and the commentator's answers, newest first (#117)
}

type Action =
  | { type: 'start'; gated: boolean }
  | { type: 'started' }
  | { type: 'failed' }
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'tick'; t: number; playing: boolean; duration: number }
  | { type: 'stats'; stats: Stats }
  | { type: 'fixed'; fix: Fix }
  | { type: 'answer'; answer: Answer }
  | { type: 'stream'; status: StreamStatus }
  | { type: 'error'; detail: string }
  | { type: 'end' }

const initial: ReplayState = {
  phase: 'idle', stream: 'ok', gated: false, now: 0, duration: 0, moments: [], lines: [], late: [], queuedMoments: [], queuedLines: [],
  ended: false, error: null, stats: null, fixes: {}, answers: [],
}

const waits = (s: ReplayState, item: { video_t?: number }) => s.gated && item.video_t !== undefined

// A reconnect gets the whole replay again, so moments and lines already held are dropped by key.
function reduce(s: ReplayState, a: Action): ReplayState {
  switch (a.type) {
    case 'start': return { ...initial, phase: 'starting', gated: a.gated, stats: s.stats }
    case 'stats': return { ...s, stats: a.stats }
    case 'started': return { ...s, phase: 'live' }
    case 'failed': return { ...s, phase: 'failed' }
    case 'moment': {
      const seen = (m: Moment) => m.idx === a.moment.idx
      if (s.moments.some(seen) || s.queuedMoments.some(seen)) return s
      return waits(s, a.moment)
        ? { ...s, queuedMoments: [...s.queuedMoments, a.moment] }
        : { ...s, moments: [...s.moments, a.moment] }
    }
    case 'line': {
      const seen = (l: Line) => l.line_id === a.line.line_id
      if (s.lines.some(seen) || s.queuedLines.some(seen)) return s
      return waits(s, a.line)
        ? { ...s, queuedLines: [...s.queuedLines, a.line] }
        : { ...s, lines: [a.line, ...s.lines] }
    }
    case 'tick': {
      // The picture's time always moves `now` (a paused seek too); only a moving picture releases.
      // Moments update the score whether live or late; only live lines become the subtitle and voice.
      const moved = s.now !== a.t || s.duration !== a.duration
      const at = { ...s, now: a.t, duration: a.duration }
      if (!a.playing) return moved ? at : s
      const m = release(s.queuedMoments, a.t)
      const l = release(s.queuedLines, a.t)
      if (m.waiting.length === s.queuedMoments.length && l.waiting.length === s.queuedLines.length) return moved ? at : s
      const released = [...l.late, ...l.live] // reversed below, so the newest live line ends up first
      return {
        ...at,
        moments: [...s.moments, ...m.late, ...m.live],
        queuedMoments: m.waiting,
        lines: [...released.reverse(), ...s.lines],
        late: [...s.late, ...l.late.map((x) => x.line_id)],
        queuedLines: l.waiting,
      }
    }
    case 'fixed': return { ...s, fixes: { ...s.fixes, [a.fix.line_id]: a.fix } }
    case 'answer':
      return s.answers.some((x) => x.line_id === a.answer.line_id) ? s : { ...s, answers: [a.answer, ...s.answers] }
    case 'stream': return { ...s, stream: a.status }
    case 'error': return { ...s, error: a.detail }
    case 'end': return { ...s, ended: true, stream: 'ok' }
  }
}

// What the picture has reached: after a backward seek, moments and lines beyond it are hidden again
// (and never re-spoken), so nothing on the page runs ahead of the video.
export function onScreen(s: ReplayState): { moments: Moment[]; lines: Line[] } {
  if (!s.gated) return { moments: s.moments, lines: s.lines }
  const reached = (x: { video_t?: number }) => x.video_t === undefined || x.video_t <= s.now
  return { moments: s.moments.filter(reached), lines: s.lines.filter(reached) }
}

// The player's clock: where the picture is, and whether it is moving. Paused or buffering = hold.
export type Clock = () => { t: number; playing: boolean; duration: number }

const TICK_MS = 100

// Runs one replay at a time: start() creates it on the server and follows its stream, reconnect()
// follows the same replay again after the stream gave up. With a video, setClock() connects the
// player, and nothing is presented or spoken until the player's time reaches it.
export function useReplay(onLine: (line: Line) => void, onRewind: () => void) {
  const [state, dispatch] = useReducer(reduce, initial)
  const replayId = useRef<string | null>(null)
  const stop = useRef<(() => void) | null>(null)
  const run = useRef(0) // ignores events from a replay that has since been replaced
  const clock = useRef<Clock | null>(null)
  const said = useRef(onLine)
  const rewound = useRef(onRewind)
  useEffect(() => {
    said.current = onLine
    rewound.current = onRewind
  }, [onLine, onRewind])

  // Speak each newly presented line once, unless it was released late.
  const spoken = useRef<string | null>(null)
  const spokenAt = useRef<number | null>(null) // video time of the line being spoken
  const newest = state.lines[0]
  useEffect(() => {
    if (!newest || newest.line_id === spoken.current) return
    spoken.current = newest.line_id
    if (!state.late.includes(newest.line_id)) {
      spokenAt.current = newest.video_t ?? null
      said.current(newest)
    }
  }, [newest, state.late])

  // Seeking back before the line being spoken stops the voice: it would describe the future.
  const at = useRef(0) // where the picture was at the last tick
  useEffect(() => {
    at.current = state.now
    if (spokenAt.current !== null && state.now < spokenAt.current) {
      spokenAt.current = null
      rewound.current()
    }
  }, [state.now])

  // With a video, read the player's clock throughout; a paused, buffering or missing player releases nothing.
  const watching = state.gated && state.phase === 'live'
  useEffect(() => {
    if (!watching) return
    const timer = window.setInterval(() => {
      const now = clock.current?.()
      // Rounded down, never up: a line tagged 8.0 s must not show while the picture is at 7.96 s.
      if (now) dispatch({ type: 'tick', t: Math.floor(now.t * 10) / 10, playing: now.playing, duration: Math.round(now.duration) })
    }, TICK_MS)
    return () => window.clearInterval(timer)
  }, [watching])

  const setClock = useCallback((c: Clock | null) => {
    clock.current = c
  }, [])

  // The video can't play for good: the replay's own clock takes the player's place from where the
  // picture was (or should have started), so the mapped lines still play rather than wait forever.
  const origin = useRef(0)
  const unGate = useCallback(() => {
    clock.current = replayClock(Math.max(at.current, origin.current))
  }, [])

  const follow = useCallback((id: string, token: number) => {
    stop.current?.()
    stop.current = followReplay(
      id,
      (e) => {
        if (run.current !== token) return
        if (e.type === 'moment') dispatch({ type: 'moment', moment: e.moment })
        if (e.type === 'line') dispatch({ type: 'line', line: e.line })
        if (e.type === 'stats') dispatch({ type: 'stats', stats: e.stats })
        if (e.type === 'fixed') dispatch({ type: 'fixed', fix: e.fix })
        if (e.type === 'answer') dispatch({ type: 'answer', answer: e.answer })
        if (e.type === 'error') dispatch({ type: 'error', detail: e.detail })
        if (e.type === 'end') dispatch({ type: 'end' })
      },
      (status) => run.current === token && dispatch({ type: 'stream', status }),
    )
  }, [])

  const start = useCallback(
    async (matchId: string, speed: number, gated: boolean, from = 0) => {
      const token = ++run.current
      stop.current?.()
      stop.current = null
      clock.current = null
      origin.current = from
      at.current = 0
      dispatch({ type: 'start', gated })
      try {
        const id = await createReplay(matchId, speed)
        if (run.current !== token) return
        replayId.current = id
        dispatch({ type: 'started' })
        follow(id, token)
      } catch {
        if (run.current === token) dispatch({ type: 'failed' })
      }
    },
    [follow],
  )

  const reconnect = useCallback(() => {
    if (!replayId.current) return
    dispatch({ type: 'stream', status: 'reconnecting' })
    follow(replayId.current, run.current)
  }, [follow])

  const leave = useCallback(() => {
    run.current++
    stop.current?.()
    stop.current = null
    clock.current = null
    replayId.current = null
  }, [])

  useEffect(() => () => stop.current?.(), [])

  // A fix's answer marks the line at once; the `fixed` event that follows on the stream is the same Fix.
  const markFixed = useCallback((fix: Fix) => dispatch({ type: 'fixed', fix }), [])

  // A viewer's question about the moment on screen; the answer shows at once (the `answer` event that
  // follows is the same one) and is returned for the caller to speak, unless the replay was replaced.
  const ask = useCallback(async (question: string, momentIdx: number): Promise<Answer | null> => {
    const token = run.current
    const id = replayId.current
    if (!id) return null
    const answer = await askCommentator(id, question, momentIdx)
    if (run.current !== token) return null
    dispatch({ type: 'answer', answer })
    return answer
  }, [])

  return { state, start, reconnect, leave, setClock, unGate, markFixed, ask }
}
