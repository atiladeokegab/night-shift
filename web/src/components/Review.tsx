import { useEffect, useRef, useState } from 'react'
import { followTraining, getLedger, getReview, getStats, postFix, timed, waitForExample } from '../api'
import { submitFix, type Refused } from '../fix'
import { adapterText, exampleText, scoreExampleLabel, TEACHES, trainingHeading } from '../proof'
import type { Fix, Ledger, LineCheckExample, ReviewItem, ScoreCheckExample, ScoreCheckStats, TrainingState } from '../types'
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
  const [example, setExample] = useState<LineCheckExample | null>(null) // the Line check example it sent (#305)
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [training, setTraining] = useState<Training | null>(null) // the last fix's Score check examples (#400)
  const [degraded, setDegraded] = useState(false) // #401: Mubit's key unset or its last call failed
  const heading = useRef<HTMLHeadingElement>(null)
  const following = useRef<AbortController | null>(null) // the panel's reads: aborted when it closes
  const closeTraining = () => (following.current?.abort(), setTraining(null))
  useEffect(() => () => following.current?.abort(), [])

  const load = () => {
    getLedger().then(setLedger, () => setLedger(null))
    getStats().then((s) => setDegraded(s.mubit === 'degraded'), () => {})
    return getReview().then(setItems, () => setFailed(true))
  }
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
        setExample(null)
        if (TEACHES.includes(reason))
          waitForExample(fix).then((ex) => ex && setExample(ex), () => {})
        following.current?.abort()
        const ctl = (following.current = new AbortController())
        setTraining({ fix, state: 'pending', before: null, examples: [], after: null })
        const mine = (f: (t: Training) => Training) => setTraining((t) => (t?.fix === fix ? f(t) : t))
        // the counts are read once the fix is saved, each giving up after 5 s: a slow /stats never holds the save
        const count = () => getStats(timed(ctl.signal, 5_000)).then((s) => s.scorecheck ?? null, () => null)
        count().then((before) => mine((t) => ({ ...t, before })))
        followTraining(fix, (state, examples) => {
          mine((t) => ({ ...t, state, examples }))
          count().then((after) => after && mine((t) => ({ ...t, after })))
        }, ctl.signal).then((state) => mine((t) => ({ ...t, state })))
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
              {item.match.split(',')[0]} · {when(item)}
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
              aria-label={`Fix this line at ${when(item)}, ${item.match}`}>
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
          The number check found these stored lines saying a number their moment's data doesn't. Fix each by hand: a
          fix that passes the number check goes back through Mubit, which records it as training data.
        </p>
        {degraded && <p className="hint" role="status">Mubit unavailable: lines use the fallback</p>}
        {said && <p className="hint" role="status">{said}</p>}
        {fixed?.mubit_request_id && (
          <p className="hint">
            {fixed.recorded ? 'Recorded in Mubit' : 'Sent to Mubit, not recorded'}: <code>{fixed.mubit_request_id}</code>
          </p>
        )}
        {example?.line_id === fixed?.line_id && example && <p className="hint" title={example.mubit_request_id ?? undefined}>{exampleText(example)}</p>}
        {training && <TrainingPanel training={training} onClose={closeTraining} />}
        {body}
        {ledger && <Corrections ledger={ledger} />}
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

interface Training {
  fix: Fix
  state: TrainingState // from this fix's own receipt (#400)
  before: ScoreCheckStats | null // /stats `scorecheck` once the fix was saved
  examples: ScoreCheckExample[] // this fix's own, by fix_uid
  after: ScoreCheckStats | null // and once its examples or receipt are in
}

const OUTCOME: Partial<Record<TrainingState, string>> = {
  pending: 'Waiting for Score check\'s receipt…',
  none: 'No new Score check example: each was already sent, or the data can\'t label it',
  held_out: 'This match is held out of training, so the eval that scores the model stays fair',
  failed: 'A Mubit call failed: nothing was sent to training',
  unknown: 'No receipt within a minute: the send may still finish. The ledger below lists every example sent.',
}

// #400: one fix becoming Score check training data, step by step, with the ids core already has. The
// heading stays neutral until this fix's receipt is in; never that a model was updated.
function TrainingPanel({ training: { fix, state, before, examples, after }, onClose }: { training: Training; onClose: () => void }) {
  const count = (sc: ScoreCheckStats | null) => sc?.examples_sent.toLocaleString('en-GB') ?? '…'
  return (
    <section className="flag glass training" aria-labelledby="training-h">
      <h2 id="training-h">{trainingHeading(state)}</h2>
      <ol aria-live="polite">
        <li>
          Fix saved{fix.mubit_request_id && <>: request <code>{fix.mubit_request_id}</code></>}
        </li>
        {examples.map((ex) => (
          <li key={ex.created_at + ex.text}>
            Score check example · {scoreExampleLabel(ex, fix)} · request <code>{ex.mubit_request_id ?? 'none'}</code>
          </li>
        ))}
        {OUTCOME[state] && <li>{OUTCOME[state]}</li>}
        <li>
          Score check examples: {count(before)} → {after ? count(after) : '…'}
        </li>
        <li>{adapterText(after ?? before)}</li>
      </ol>
      <button className="btn" onClick={onClose}>Close</button>
    </section>
  )
}

// Every correction sent to Mubit, newest first, each with the session and request that find it in Mubit's
// console. "Sent", never "kept": only the console says what Mubit kept.
function Corrections({ ledger }: { ledger: Ledger }) {
  return (
    <section className="ledger" aria-labelledby="ledger-h">
      <h2 id="ledger-h">Corrections sent to Mubit</h2>
      <p className="hint">
        {ledger.sent} example{ledger.sent === 1 ? '' : 's'} sent to Score check · the newest {ledger.rows.length}{' '}
        correction{ledger.rows.length === 1 ? '' : 's'} below
      </p>
      {ledger.rows.length > 0 && (
        <ul className="queue">
          {ledger.rows.map((r, i) => (
            <li key={`${r.request_id}-${i}`} className="flag glass">
              <p className="label">
                {r.at?.slice(0, 16).replace('T', ' ')} · {r.source} · {r.task}
                {r.match ? ` · ${r.match}, moment ${r.idx}` : ''}
              </p>
              {r.text && <div className="said">{r.text}</div>}
              {r.score && <p className="moment"><span>Data: {r.score}.</span></p>}
              {r.wrong.length > 0 && (
                <ul className="wrong">
                  {r.wrong.map((w) => (
                    <li key={w}>{w[0].toUpperCase() + w.slice(1)}</li>
                  ))}
                </ul>
              )}
              <p className="hint">
                Session <code>{r.session ?? 'unknown'}</code> · request <code>{r.request_id ?? 'none'}</code>
                {r.link && (
                  <>
                    {' · '}
                    <a href={r.link} target="_blank" rel="noreferrer">Open in Mubit</a>
                  </>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
