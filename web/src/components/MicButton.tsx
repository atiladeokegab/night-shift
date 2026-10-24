import { useEffect, useRef, useState } from 'react'
import { listen, recognizer } from '../voice'

interface Props {
  disabled: boolean
  onHeard: (text: string) => void // the words so far, shown in the Ask box
  onSend: (text: string) => void
  onHint: (hint: string) => void
}

const make = recognizer()

// Ask by voice (#139): hold the mic (or the space bar while no field has focus) and talk; letting go, or a
// final result, sends what was heard through the Ask box. Hidden where the browser has no speech recognition.
export function MicButton({ disabled, onHeard, onSend, onHint }: Props) {
  const [listening, setListening] = useState(false)
  const release = useRef<(() => void) | null>(null)
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
      heard: (t) => latest.current.onHeard(t),
      done: (t) => over(() => latest.current.onSend(t)),
      hint: (h) => over(() => latest.current.onHint(h)),
    })
  }
  const letGo = () => release.current?.()

  useEffect(() => {
    if (!make) return
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
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <rect x="5.5" y="1.5" width="5" height="8.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M3 8a5 5 0 0 0 10 0M8 13v2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    </button>
  )
}
