import { useEffect, useRef, useState } from 'react'
import { getReview, postFix } from '../api'
import { submitFix } from '../fix'
import type { ReviewItem } from '../types'
import { FixSheet, type FixPhase } from './FixSheet'
import { Nav, type Screen } from './Nav'

// #171: stored lines the number check flags, newest first. Each is fixed with the same fix as a replay's
// (POST /lines/{id}/fix), so Mubit records it for training the same way (#161), and its card leaves.
export function Review({ onGo }: { onGo: (screen: Screen) => void }) {
  const [items, setItems] = useState<ReviewItem[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [fixing, setFixing] = useState<{ item: ReviewItem; phase: FixPhase } | null>(null)
  const [said, setSaid] = useState('')
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
        heading.current?.focus() // its card is gone: focus goes back to the top of the queue
      },
      // A 503 stores nothing (CONTRACT.md): the sheet stays open with the text to send again.
      () => setFixing({ item, phase: 'error' }),
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
              <span className="label">What's wrong</span>
              <ul className="wrong">
                {item.wrong.map((w) => (
                  <li key={w}>{w[0].toUpperCase() + w.slice(1)}</li>
                ))}
              </ul>
            </div>
            <div className="field">
              <span className="label">Touchline said</span>
              <div className="said">{item.text}</div>
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
          {items?.length ? `${items.length} line${items.length === 1 ? '' : 's'} to fix` : 'Lines to fix'}
        </h1>
        <p className="lede">
          The number check found these stored lines saying a number their moment's data doesn't. Fix each by hand: the
          fix goes back through Mubit, which trains on it.
        </p>
        {said && <p className="hint" role="status">{said}</p>}
        {body}
      </main>
      {fixing && (
        <FixSheet key={fixing.item.line_id} line={fixing.item} phase={fixing.phase} onSend={send}
          onCancel={() => setFixing(null)} />
      )}
    </div>
  )
}

// "Q3 06:22", "Over 19.6", "Lap 28", "41:02": where in the match the moment is.
function when(item: ReviewItem): string {
  if (item.sport === 'basketball') return `Q${item.period} ${item.clock}`
  if (item.sport === 'cricket') return `Over ${item.clock}`
  if (item.sport === 'f1') return `Lap ${item.period ?? ''}`.trim()
  return item.clock ?? ''
}
