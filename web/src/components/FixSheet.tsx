import { useEffect, useRef, useState } from 'react'
import type { Line } from '../types'

const REASONS = ['Wrong fact', 'Wrong player', 'Wrong score', 'Tone', 'Other']

export type FixPhase = 'edit' | 'sending' | 'error'

interface Props {
  line: Line
  phase: FixPhase
  onSend: (text: string, reason: string) => void
  onCancel: () => void
}

// The producer fix (docs/design.md "Fix sheet"; POST /lines/{id}/fix, A-4.1). On a failed send the
// sheet stays open with the producer's text, so it can be sent again: a 503 stores nothing.
export function FixSheet({ line, phase, onSend, onCancel }: Props) {
  const [text, setText] = useState(line.text)
  const unchanged = !text.trim() || text.trim() === line.text.trim() // nothing to send yet
  const [reason, setReason] = useState(REASONS[0])
  const box = useRef<HTMLTextAreaElement>(null)
  const sending = phase === 'sending'

  useEffect(() => {
    box.current?.focus()
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && !sending && onCancel()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [sending, onCancel])

  return (
    <div className="scrim" onClick={(e) => e.target === e.currentTarget && !sending && onCancel()}>
      <div className="sheet glass" role="dialog" aria-modal="true" aria-labelledby="fix-h">
        <h2 id="fix-h">Fix this line</h2>
        <div className="field">
          <span className="label">Touchline said</span>
          <div className="said">{line.text}</div>
        </div>
        <div className="field">
          <label className="label" htmlFor="fix-text">Corrected line</label>
          <textarea id="fix-text" ref={box} value={text} disabled={sending} onChange={(e) => setText(e.target.value)} />
          {unchanged && <p className="hint">Type the corrected line.</p>}
        </div>
        <div className="field">
          <span className="label">What was wrong</span>
          <div className="chips" role="radiogroup" aria-label="What was wrong">
            {REASONS.map((r) => (
              <label key={r}>
                <input type="radio" name="reason" value={r} checked={reason === r} disabled={sending} onChange={() => setReason(r)} />
                <span>{r}</span>
              </label>
            ))}
          </div>
        </div>
        {phase === 'error' && <p className="err-text" role="alert">Fix not saved. Check the connection and send again.</p>}
        <div className="actions">
          <button className="btn primary" disabled={sending || unchanged} onClick={() => onSend(text.trim(), reason)}>
            {sending ? <><span className="spin sm" />Sending fix…</> : 'Send fix'}
          </button>
          <span className="spacer" />
          <button className="btn" disabled={sending} onClick={onCancel}>Cancel</button>
        </div>
        <p className="hint">Your fix goes back through Mubit and is kept beside the original.</p>
      </div>
    </div>
  )
}
