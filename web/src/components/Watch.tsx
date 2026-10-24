import { useEffect, useRef, useState } from 'react'
import { canWatch, watch, type Media } from '../look'

interface Props {
  onLook: (image: string, t: number) => Promise<boolean> // one frame and the video time; false: stop
  time: () => number // where the picture is, in video seconds
  media?: Partial<Media> // the browser's own unless a test passes one
}

// Let them watch (#291), in the controls of a match with video: the viewer shares this tab, and while it is
// shared a "They're watching" chip with Stop shows. Hidden where the browser can't share a tab.
export function Watch({ onLook, time, media = globalThis.navigator?.mediaDevices }: Props) {
  const [state, setState] = useState<'off' | 'asking' | 'on' | 'done'>('off')
  const stop = useRef<(() => void) | null>(null)
  const now = useRef(time)
  useEffect(() => {
    now.current = time
  }, [time])
  useEffect(() => () => stop.current?.(), []) // a new replay or page: sharing ends with it
  if (!canWatch(media) || state === 'done') return null

  const start = async () => {
    setState('asking')
    let refused = false // the server takes no more frames: the replay is over, so no button again
    const send = async (image: string) => {
      refused = !(await onLook(image, now.current()))
      return !refused
    }
    let ended = false
    try {
      const end = await watch(media, send, () => {
        ended = true
        stop.current = null
        setState(refused ? 'done' : 'off')
      })
      if (!ended) {
        stop.current = end
        setState('on')
      }
    } catch {
      setState('off') // the viewer said no to sharing
    }
  }
  return <Watching on={state === 'on'} asking={state === 'asking'} onStart={start} onStop={() => stop.current?.()} />
}

// The button, or the chip while they watch; the status line tells a screen reader either way.
export function Watching({ on, asking = false, onStart, onStop }: { on: boolean; asking?: boolean; onStart: () => void; onStop: () => void }) {
  return (
    <>
      <span className="sr-only" role="status">{on ? "They're watching the screen" : ''}</span>
      {on ? (
        <span className="watching">
          <span className="chip"><b aria-hidden />They're watching</span>
          <button className="ctl eyes-btn" aria-label="Stop: they stop watching" onClick={onStop}><span>Stop</span></button>
        </span>
      ) : (
        <button className="ctl eyes-btn watch-btn" disabled={asking} aria-label="Let them watch" title="Share this tab so the commentators see the picture" onClick={onStart}>
          <svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4">
            <rect x="1.5" y="2.5" width="13" height="9" rx="1.5" /><path d="M5.5 14h5M8 11.5V14" />
          </svg>
          <span>Let them watch</span>
        </button>
      )}
    </>
  )
}
