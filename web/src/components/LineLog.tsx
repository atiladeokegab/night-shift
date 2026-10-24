import { useEffect, useRef, useState, type FormEvent } from 'react'
import { answeredAt, isStale, withAnswers } from '../ask'
import { names, shortName } from '../follow'
import { MicButton, MicOn, type Mic } from './MicButton'
import { clockText } from '../moment'
import { WHERE } from '../quiet'
import type { Answer, Fix, Line, Moment } from '../types'

interface Props {
  lines: Line[] // newest first, only what the picture has reached
  late: string[] // released after the video had moved past them: never shown or spoken
  fixes: Record<string, Fix>
  moments: Moment[]
  onFix: (line: Line) => void
  answers: Answer[] // newest first
  interrupted?: string[] // answers a decisive moment cut off: marked, with "Hear it again"
  onHear?: (answer: Answer) => void
  onAsk: ((question: string) => Promise<void>) | null // null until a moment is on screen
  shooter: string | null // the latest shooter on screen, in a sport with a shot map (#120)
  onShots: (name: string) => void
  followed?: string | null // the followed player's lines stand out (#140)
  voiced?: boolean // #170: an answer is spoken, so a screen reader hears only that it is ready
  roster?: string[] // everyone in the match, so a shared surname needs the full name
  onUnfollow?: () => void
  mic?: Mic // Mic on (#286)
}

// The Lines card (docs/design.md): every line so far, newest first, with its clock, its speaker, the model's
// first-text-word time (the number; its name in the title, #153) and "Fix". A fixed line shows the correction over the struck-through original. Viewers' questions and
// the commentator's answers (#117) sit among the lines at the moment they were asked.
// "3 called · 15 earlier": lines a jump (#163) brought from an earlier replay were not called this time.
function count(lines: Line[]): string {
  const earlier = lines.filter((l) => l.history).length
  const called = lines.length - earlier
  return [called && `${called} called`, earlier && `${earlier} earlier`].filter(Boolean).join(' · ')
}

export function LineLog({ lines, late, fixes, moments, onFix, answers, interrupted = [], onHear, onAsk, shooter, onShots, followed, roster, onUnfollow, voiced, mic }: Props) {
  const said = (l: Line) => fixes[l.line_id]?.corrected_text ?? l.text
  const theirs = followed ? lines.filter((l) => names(said(l), followed, roster)).length : 0
  return (
    <section className="panel lines glass" aria-label="Lines">
      <div className="panel-h">
        <h3>Lines</h3>
        <span className="label">{count(lines)}</span>
      </div>
      <AskBox onAsk={onAsk} mic={mic} />
      {followed && (
        <div className="following">
          <span>Following <b>{followed}</b> · {theirs} {theirs === 1 ? 'line' : 'lines'}</span>
          {onUnfollow && <button className="btn sm" onClick={onUnfollow}>Clear</button>}
        </div>
      )}
      {shooter && <button className="btn sm shots-open" onClick={() => onShots(shooter)}>Shot map · {shooter}</button>}
      <p className="sr-only" aria-live="polite">{!answers[0] ? '' : voiced && !answers[0].off_air ? 'Answer ready' : `Touchline: ${answers[0].text}`}</p>
      {lines.length === 0 && answers.length === 0 ? (
        <p className="hint">Lines appear here as Touchline calls them.</p>
      ) : (
        <ul className="log">
          {withAnswers(lines, answers).map(({ line: l, answer: a }) => {
            if (a) {
              const at = answeredAt(a, moments)
              return (
                <li key={a.line_id} className={`qa${a.off_air ? ' off' : ''}${isStale(a, moments) ? ' stale' : ''}`}>
                  <span className="when">Ask</span>
                  <div className="text">
                    <div className="q">{a.question}{at && <span className="at nw"> · {at}</span>}</div>
                    <span>{a.text}</span>
                  </div>
                  {interrupted.includes(a.line_id) && (
                    <>
                      {onHear && <button className="btn sm" onClick={() => onHear(a)}>Hear it again</button>}
                      <div className="meta-l"><span className="pill late">Interrupted</span></div>
                    </>
                  )}
                </li>
              )
            }
            const m = moments.find((x) => x.idx === l.moment_idx)
            const fix = fixes[l.line_id]
            const isLate = late.includes(l.line_id)
            const mine = names(said(l), followed, roster)
            const firstWord = l.first_word_ms != null // undefined or null: only the whole reply was timed
            const ms = l.first_word_ms ?? l.latency_ms
            const took = `${(ms / 1000).toFixed(2)} s`
            return (
              <li key={l.line_id} className={fix || l.fixed ? 'fixed' : isLate ? 'late' : undefined} data-follow={mine || undefined}>
                <span className="when num">{m ? clockText(m, true) : ''}</span>
                <div className="text">
                  <span>{fix ? fix.corrected_text : l.text}</span>
                  {fix && <div className="orig">{l.text}</div>}
                </div>
                <button className="btn sm" disabled={!!fix} onClick={() => onFix(l)} aria-label={`Fix the line${m ? ` at ${clockText(m, true)}` : ''}`}>
                  Fix
                </button>
                <div className="meta-l">
                  <span className={`chip ${l.speaker ?? 'lead'}`}>{l.speaker === 'analyst' ? 'Analyst' : 'Lead'}</span>
                  {l.history
                    ? <span className="num">From an earlier replay</span> // a jump (#163) never called it, so no timing
                    : l.fixed
                      ? <span className="num">Not called</span> // a producer's fix (#232): no model, so no timing
                      : <span className="num" title={`${firstWord ? 'model first text word' : 'model reply'} ${took}`}>{took}</span>}
                  {l.served_by && <span className="pill served" title="Served by: the model Mubit's reply said answered">{l.served_by}</span>}
                  {mine && <span className="pill follow">{shortName(followed!)}</span>}
                  {fix && <span className="pill fixed">Fixed</span>}
                  {l.fixed && !fix && <span className="pill fixed producer">Fixed by producer</span>}
                  {isLate && !fix && <span className="pill late" title="The video had moved past it, so it was not shown or spoken">Late</span>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// "Ask the commentator" (#117): text in, or by voice (#139), one question at a time; the answer lands in
// the log and is spoken. "Where are we?" (#186) is one press, or the W key while no field has focus.
// Mic on (#286) listens hands-free; hold-to-talk stands down meanwhile.
function AskBox({ onAsk, mic }: { onAsk: Props['onAsk']; mic?: Mic }) {
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [handsFree, setHandsFree] = useState(false)
  const [hint, setHint] = useState('') // the mic's one-line hint: denied, or nothing heard
  const send = async (e: FormEvent) => {
    e.preventDefault()
    await ask(question)
  }
  const ask = async (text: string) => {
    const q = text.trim()
    if (!q || asking || !onAsk) return
    setAsking(true)
    try {
      await onAsk(q)
      setQuestion('')
    } finally {
      setAsking(false)
    }
  }
  const voice = { onHeard: (t: string) => (setHint(''), setQuestion(t)), onSend: (t: string) => (setQuestion(t), void ask(t)),
    onHint: (h: string) => (setQuestion(''), setHint(h)) }
  const latest = useRef(ask) // the window's key handler asks with the newest state
  useEffect(() => {
    latest.current = ask
  })
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'w' || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return
      if ((e.target as Element | null)?.closest?.('input, textarea, select, [contenteditable]')) return
      e.preventDefault()
      void latest.current(WHERE)
    }
    window.addEventListener('keydown', down)
    return () => window.removeEventListener('keydown', down)
  }, [])
  return (
    <>
      <button type="button" className="btn where" aria-keyshortcuts="W" title="Where are we? (W)" disabled={!onAsk || asking}
        onClick={() => void ask(WHERE)}>
        {WHERE}
      </button>
      <form className="ask" onSubmit={send}>
        <label className="sr-only" htmlFor="ask-q">Ask the commentator</label>
        {/* A one-row box that grows, so a long question reads from its start (#153); Enter sends, as the input did. */}
        <textarea id="ask-q" rows={1} value={question} maxLength={200} readOnly={asking} disabled={!onAsk} autoComplete="off" enterKeyHint="send"
          placeholder={!onAsk ? 'Ask once play starts' : hint || 'Ask the commentator…'} onChange={(e) => setQuestion(e.target.value.replace(/\n/g, ' '))}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && (e.preventDefault(), e.currentTarget.form?.requestSubmit())} />
        <MicButton disabled={!onAsk || asking || handsFree} {...voice} />
        <button className="btn sm primary" disabled={!onAsk || asking || !question.trim()}>
          {asking ? <><span className="spin sm" />Asking…</> : 'Ask'}
        </button>
      </form>
      <MicOn on={handsFree} onToggle={setHandsFree} ready={!!onAsk} mic={mic} disabled={!onAsk || asking} {...voice} />
    </>
  )
}
