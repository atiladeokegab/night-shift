import { useCallback, useEffect, useReducer, useRef } from 'react'
import { createReplay, followReplay, type StreamStatus } from './api'
import type { Line, Moment, Stats } from './types'

export interface ReplayState {
  phase: 'idle' | 'starting' | 'live' | 'failed'
  stream: StreamStatus
  moments: Moment[]
  lines: Line[] // newest first
  ended: boolean
  error: string | null // a server `error` event: the commentator failed mid-replay
  stats: Stats | null // the latest `stats` event; store-wide, so it outlives a single replay
}

type Action =
  | { type: 'start' }
  | { type: 'started' }
  | { type: 'failed' }
  | { type: 'moment'; moment: Moment }
  | { type: 'line'; line: Line }
  | { type: 'stats'; stats: Stats }
  | { type: 'stream'; status: StreamStatus }
  | { type: 'error'; detail: string }
  | { type: 'end' }

const initial: ReplayState = { phase: 'idle', stream: 'ok', moments: [], lines: [], ended: false, error: null, stats: null }

// A reconnect gets the whole replay again, so moments and lines already held are dropped by key.
function reduce(s: ReplayState, a: Action): ReplayState {
  switch (a.type) {
    case 'start': return { ...initial, phase: 'starting', stats: s.stats }
    case 'started': return { ...s, phase: 'live' }
    case 'failed': return { ...s, phase: 'failed' }
    case 'moment':
      return s.moments.some((m) => m.idx === a.moment.idx) ? s : { ...s, moments: [...s.moments, a.moment] }
    case 'line':
      return s.lines.some((l) => l.line_id === a.line.line_id) ? s : { ...s, lines: [a.line, ...s.lines] }
    case 'stats': return { ...s, stats: a.stats }
    case 'stream': return { ...s, stream: a.status }
    case 'error': return { ...s, error: a.detail }
    case 'end': return { ...s, ended: true, stream: 'ok' }
  }
}

// Runs one replay at a time: start() creates it on the server and follows its stream,
// reconnect() follows the same replay again after the stream gave up.
export function useReplay(onLine: (line: Line) => void) {
  const [state, dispatch] = useReducer(reduce, initial)
  const replayId = useRef<string | null>(null)
  const stop = useRef<(() => void) | null>(null)
  const run = useRef(0) // ignores events from a replay that has since been replaced
  const said = useRef(onLine)
  useEffect(() => {
    said.current = onLine
  }, [onLine])

  const follow = useCallback((id: string, token: number) => {
    stop.current?.()
    stop.current = followReplay(
      id,
      (e) => {
        if (run.current !== token) return
        if (e.type === 'moment') dispatch({ type: 'moment', moment: e.moment })
        if (e.type === 'line') {
          dispatch({ type: 'line', line: e.line })
          said.current(e.line)
        }
        if (e.type === 'stats') dispatch({ type: 'stats', stats: e.stats })
        if (e.type === 'error') dispatch({ type: 'error', detail: e.detail })
        if (e.type === 'end') dispatch({ type: 'end' })
      },
      (status) => run.current === token && dispatch({ type: 'stream', status }),
    )
  }, [])

  const start = useCallback(
    async (matchId: string, speed: number) => {
      const token = ++run.current
      stop.current?.()
      stop.current = null
      dispatch({ type: 'start' })
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
    replayId.current = null
  }, [])

  useEffect(() => () => stop.current?.(), [])

  return { state, start, reconnect, leave }
}
