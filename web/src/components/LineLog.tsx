import { useState, type FormEvent } from 'react'
import { withAnswers } from '../ask'
import { names, shortName } from '../follow'
import { MicButton } from './MicButton'
import { clockText } from '../moment'
import type { Answer, Fix, Line, Moment } from '../types'

interface Props {
  lines: Line[] // newest first, only what the picture has reached
  late: string[] // released after the video had moved past them: never shown or spoken
  fixes: Record<string, Fix>
  moments: Moment[]
  onFix: (line: Line) => void
  answers: Answer[] // newest first
  onAsk: ((question: string) => Promise<void>) | null // null until a moment is on screen
  shooter: string | null // the latest shooter on screen, in a sport with a shot map (#120)
  onShots: (name: string) => void
  followed?: string | null // the followed player's lines stand out (#140)
  roster?: string[] // everyone in the match, so a shared surname needs the full name
  onUnfollow?: () => void
}

// The Lines card (docs/design.md): every line so far, newest first, with its clock, its speaker, the model's
// first-text-word time (the number; its name in the title, #153) and "Fix". A fixed line shows the correction over the struck-through original. Viewers' questions and
// the commentator's answers (#117) sit among the lines at the moment they were asked.
export function LineLog({ lines, late, fixes, moments, onFix, answers, onAsk, shooter, onShots, followed, roster, onUnfollow }: Props) {
  const said = (l: Line) => fixes[l.line_id]?.corrected_text ?? l.text
  const theirs = followed ? lines.filter((l) => names(said(l), followed, roster)).length : 0
  return (
    <section className="panel lines glass" aria-label="Lines">
      <div className="panel-h">
        <h3>Lines</h3>
        <span className="label">{lines.length ? `${lines.length} called` : ''}</span>
      </div>
      <AskBox onAsk={onAsk} />
      {followed && (
        <div className="following">
          <span>Following <b>{followed}</b> · {theirs} {theirs === 1 ? 'line' : 'lines'}</span>
          {onUnfollow && <button className="btn sm" onClick={onUnfollow}>Clear</button>}
        </div>
      )}
      {shooter && <button className="btn sm shots-open" onClick={() => onShots(shooter)}>Shot map · {shooter}</button>}
      <p className="sr-only" aria-live="polite">{answers[0] ? `Touchline: ${answers[0].text}` : ''}</p>
      {lines.length === 0 && answers.length === 0 ? (
        <p className="hint">Lines appear here as Touchline calls them.</p>
      ) : (
        <ul className="log">
          {withAnswers(lines, answers).map(({ line: l, answer: a }) => {
            if (a) {
              return (
                <li key={a.line_id} className={`qa${a.off_air ? ' off' : ''}`}>
                  <span className="when">Ask</span>
                  <div className="text">
                    <div className="q">{a.question}</div>
                    <span>{a.text}</span>
                  </div>
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
              <li key={l.line_id} className={fix ? 'fixed' : isLate ? 'late' : undefined} data-follow={mine || undefined}>
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
                  <span className="num" title={`${firstWord ? 'model first text word' : 'model reply'} ${took}`}>{took}</span>
                  {mine && <span className="pill follow">{shortName(followed!)}</span>}
                  {fix && <span className="pill fixed">Fixed</span>}
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
// the log and is spoken.
function AskBox({ onAsk }: { onAsk: Props['onAsk'] }) {
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
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
  return (
    <form className="ask" onSubmit={send}>
      <label className="sr-only" htmlFor="ask-q">Ask the commentator</label>
      {/* A one-row box that grows, so a long question reads from its start (#153); Enter sends, as the input did. */}
      <textarea id="ask-q" rows={1} value={question} maxLength={200} readOnly={asking} disabled={!onAsk} autoComplete="off" enterKeyHint="send"
        placeholder={!onAsk ? 'Ask once play starts' : hint || 'Ask the commentator…'} onChange={(e) => setQuestion(e.target.value.replace(/\n/g, ' '))}
        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && (e.preventDefault(), e.currentTarget.form?.requestSubmit())} />
      <MicButton disabled={!onAsk || asking} onHeard={(t) => (setHint(''), setQuestion(t))} onSend={(t) => (setQuestion(t), void ask(t))}
        onHint={(h) => (setQuestion(''), setHint(h))} />
      <button className="btn sm primary" disabled={!onAsk || asking || !question.trim()}>
        {asking ? <><span className="spin sm" />Asking…</> : 'Ask'}
      </button>
    </form>
  )
}
