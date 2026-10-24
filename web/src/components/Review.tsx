import { useEffect, useRef, useState } from 'react'
import { getReview, postFix } from '../api'
import { submitFix, type Refused } from '../fix'
import type { Fix, ReviewItem } from '../types'
import { FixSheet, type FixPhase } from './FixSheet'
import { Nav, type Screen } from './Nav'

// #171: stored lines the number check flags, newest first, one card per mistake (#227). Each is fixed with the same fix as a replay's
// (POST /lines/{id}/fix), so Mubit records it for training the same way (#161), and its card leaves.
export function Review({ onGo }: { onGo: (screen: Screen) => void }) {
  const [items, setItems] = useState<ReviewItem[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [fixing, setFixing] = useState<{ item: ReviewItem; phase: FixPhase; refused?: Refused } | null>(null)
  const [said, setSaid] = useState('')
  const [fixed, setFixed] = useState<Fix | null>(null) // the last fix sent: its Mubit request id (#239)
  const heading = useRef<HTMLHeadingElement>(null)

  const load = () => getReview().then(setItems, () => setFailed(true))
  useEffect(() => void load(), [])
  const retry = () => {
    setFailed(false)
    load()
  }

  const send = async (text: string, reason: string) => {
    if (!fixing) return
    const { item } = fixing
    setFixing({ item, phase: 'sending' })
    await submitFix(
      () => postFix(item.line_id, text, reason),
      () => true,
      (fix) => {
        setItems((xs) => xs && xs.filter((x) => x.line_id !== item.line_id))
        setFixing(null)
        setSaid(fix.recorded ? 'Fix sent. Mubit records it for training.' : 'Fix sent. Kept beside the original.')
        setFixed(fix)
        heading.current?.focus() // its card is gone: focus goes back to the top of the queue
      },
      // A 503 stores nothing (CONTRACT.md): the sheet stays open with the text to send again.
      (refused) => setFixing({ item, phase: 'error', refused }),
    )
  }

  let body
  if (failed)
    body = (
      <p className="hint" role="alert">
        Couldn't load the queue. <button className="btn sm" onClick={retry}>Try again</button>
      </p>
    )
  else if (!items) body = <p className="hint" role="status">Loading flagged lines…</p>
  else if (!items.length) body = <p className="hint">Nothing to review. Every stored line's numbers match its moment.</p>
  else
    body = (
      <ul className="queue">
        {items.map((item) => (
          <li key={item.line_id} className="flag glass">
            <p className="label">
              {item.match} · {when(item)}
            </p>
            <p className="moment">
              {item.play}. <span>{item.score}.</span>
            </p>
            <div className="field">
              <span className="label">What's wrong{item.later_check ? ' · found by a later check' : ''}</span>
              <ul className="wrong">
                {item.wrong.map((w) => (
                  <li key={w}>{w[0].toUpperCase() + w.slice(1)}</li>
                ))}
              </ul>
            </div>
            <div className="field">
              <span className="label">Touchline said{item.lines > 1 ? ` · ×${item.lines}` : ''}</span>
              <div className="said">{item.text}</div>
              {item.others.length > 0 && (
                <details className="others">
                  <summary>
                    {item.others.length} more wording{item.others.length === 1 ? '' : 's'} of this mistake
                  </summary>
                  <ul>
                    {item.others.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            <button className="btn primary" onClick={() => setFixing({ item, phase: 'edit' })}
              aria-label={`Fix the line at ${when(item)}, ${item.match}`}>
              Fix this line
            </button>
          </li>
        ))}
      </ul>
    )

  return (
    <div className="page">
      <Nav current="review" onGo={onGo} />
      <main className="wrap review">
        <p className="eyebrow">Review</p>
        <h1 ref={heading} tabIndex={-1}>
          {items?.length ? queueTitle(items) : 'Lines to fix'}
        </h1>
        <p className="lede">
          The number check found these stored lines saying a number their moment's data doesn't. Fix each by hand: the
          fix goes back through Mubit, which records it as training data.
        </p>
        {said && <p className="hint" role="status">{said}</p>}
        {fixed?.mubit_request_id && (
          <p className="hint">
            {fixed.recorded ? 'Recorded in Mubit' : 'Sent to Mubit, not recorded'}: <code>{fixed.mubit_request_id}</code>
          </p>
        )}
        {body}
      </main>
      {fixing && (
        <FixSheet key={fixing.item.line_id} line={fixing.item} phase={fixing.phase} refused={fixing.refused} onSend={send}
          onCancel={() => setFixing(null)} />
      )}
    </div>
  )
}

// "25 mistakes to fix · 87 lines": each card is one mistake, maybe said in several wordings (#227).
function queueTitle(items: ReviewItem[]): string {
  const lines = items.reduce((n, x) => n + x.lines, 0)
  return `${items.length} mistake${items.length === 1 ? '' : 's'} to fix · ${lines} line${lines === 1 ? '' : 's'}`
}

// "Q3 06:22", "Over 19.6", "Lap 28", "41:02": where in the match the moment is.
function when(item: ReviewItem): string {
  if (item.sport === 'basketball') return `Q${item.period} ${item.clock}`
  if (item.sport === 'cricket') return `Over ${item.clock}`
  if (item.sport === 'f1') return `Lap ${item.period ?? ''}`.trim()
  return item.clock ?? ''
}
