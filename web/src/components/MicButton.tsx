import { useEffect, useRef, useState } from 'react'
import { listen, listenAlways, recognizer } from '../voice'

interface Props {
  disabled: boolean
  onHeard: (text: string) => void // the words so far, shown in the Ask box
  onSend: (text: string) => void
  onHint: (hint: string) => void
}

const make = recognizer()

const icon = (
  <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
    <rect x="5.5" y="1.5" width="5" height="8.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
    <path d="M3 8a5 5 0 0 0 10 0M8 13v2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
  </svg>
)

// Ask by voice (#139): hold the mic (or the space bar while no field has focus) and talk; letting go, or a
// final result, sends what was heard through the Ask box. Hidden where the browser has no speech recognition.
export function MicButton({ disabled, onHeard, onSend, onHint }: Props) {
  const [listening, setListening] = useState(false)
  const release = useRef<(() => void) | null>(null)
  const mounted = useRef(false)
  const latest = useRef({ disabled, onHeard, onSend, onHint }) // the window's key handlers see the newest props
  useEffect(() => {
    latest.current = { disabled, onHeard, onSend, onHint }
  })

  const press = () => {
    if (!make || release.current || latest.current.disabled) return
    const over = (then: () => void) => {
      release.current = null
      setListening(false)
      then()
    }
    setListening(true)
    latest.current.onHeard('')
    release.current = listen(make, {
      heard: (t) => mounted.current && latest.current.onHeard(t),
      done: (t) => mounted.current && over(() => latest.current.onSend(t)),
      hint: (h) => mounted.current && over(() => latest.current.onHint(h)),
    })
  }
  const letGo = () => release.current?.()

  useEffect(() => {
    if (!make) return
    mounted.current = true
    // Space is push-to-talk unless a field or another button has focus (it types or clicks there).
    const away = (e: KeyboardEvent) =>
      e.code !== 'Space' || (e.target as Element | null)?.closest?.('input, textarea, select, [contenteditable], button:not(.mic)')
    const down = (e: KeyboardEvent) => {
      if (away(e)) return
      e.preventDefault()
      if (!e.repeat) press()
    }
    const up = (e: KeyboardEvent) => {
      if (away(e)) return
      e.preventDefault()
      letGo()
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      mounted.current = false
      release.current?.()
    }
  }, [])

  if (!make) return null
  return (
    <button type="button" className={`btn sm mic${listening ? ' primary' : ''}`} disabled={disabled} aria-pressed={listening}
      aria-label={listening ? 'Listening: let go to ask' : 'Hold to ask by voice (or hold space)'} title="Hold to talk"
      style={{ touchAction: 'none', userSelect: 'none' }}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        press()
      }}
      onPointerUp={letGo} onPointerCancel={letGo} onContextMenu={(e) => e.preventDefault()}>
      {icon}
    </button>
  )
}

export interface Mic {
  airing: () => string[] // what the page is saying, and the line before it, until 3 s after each ends
  duck: () => void // hushes the commentary: the viewer is talking
}

interface OnProps extends Props {
  on: boolean
  onToggle: (on: boolean) => void
  ready: boolean // a moment is on screen to ask about; until then it can't be turned on
  mic?: Mic
}

// Mic on (#286): one press and the page listens until it is pressed again, so the viewer talks to Touchline
// whenever they like. Their voice hushes the commentary at once; the finished sentence is asked as a typed
// question is, and the commentary carries on. Hidden where the browser has no speech recognition.
export function MicOn({ on, onToggle, ready, mic, disabled, onHeard, onSend, onHint }: OnProps) {
  const latest = useRef({ disabled, mic, onHeard, onSend, onHint, onToggle })
  useEffect(() => {
    latest.current = { disabled, mic, onHeard, onSend, onHint, onToggle }
  })
  useEffect(() => {
    if (!on || !make) return
    const now = () => latest.current
    return listenAlways(make, {
      barge: () => now().mic?.duck(),
      heard: (t) => now().disabled || now().onHeard(t),
      done: (t) => (now().disabled ? now().onHeard('') : now().onSend(t)), // one question at a time
      hint: (h) => (now().onToggle(false), now().onHint(h)),
    }, () => now().mic?.airing() ?? [])
  }, [on])

  if (!make) return null
  return (
    // One line in both states, with room under it for the pressed button's glow.
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 38, marginBottom: 14 }}>
      <button type="button" className={`btn sm${on ? ' primary' : ''}`} aria-pressed={on} disabled={!on && !ready}
        onClick={() => onToggle(!on)}
        style={{ flex: 'none', whiteSpace: 'nowrap', gap: 6 }}>
        {icon}Mic on
      </button>
      <p className="hint" aria-live="polite" style={{ minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {on ? 'Listening' : 'Hands-free'} · use headphones
      </p>
    </div>
  )
}
