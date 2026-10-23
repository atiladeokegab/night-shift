import { clockText } from '../moment'
import type { Fix, Line, Moment } from '../types'

interface Props {
  lines: Line[] // newest first, only what the picture has reached
  late: string[] // released after the video had moved past them: never shown or spoken
  fixes: Record<string, Fix>
  moments: Moment[]
  onFix: (line: Line) => void
}

// The Lines card (docs/design.md): every line so far, newest first, with its clock, the model's
// first-text-word time ("first word" in the mockup: the #37 review asked for the measured thing's name)
// and "Fix". A fixed line shows the correction over the struck-through original.
export function LineLog({ lines, late, fixes, moments, onFix }: Props) {
  return (
    <section className="panel lines glass" aria-label="Lines">
      <div className="panel-h">
        <h3>Lines</h3>
        <span className="label">{lines.length ? `${lines.length} called` : ''}</span>
      </div>
      {lines.length === 0 ? (
        <p className="hint">Lines appear here as Touchline calls them.</p>
      ) : (
        <ul className="log">
          {lines.map((l) => {
            const m = moments.find((x) => x.idx === l.moment_idx)
            const fix = fixes[l.line_id]
            const isLate = late.includes(l.line_id)
            const firstWord = l.first_word_ms !== undefined
            const ms = l.first_word_ms ?? l.latency_ms
            return (
              <li key={l.line_id} className={fix ? 'fixed' : isLate ? 'late' : undefined}>
                <span className="when num">{m ? clockText(m, true) : ''}</span>
                <div className="text">
                  <span>{fix ? fix.corrected_text : l.text}</span>
                  {fix && <div className="orig">{l.text}</div>}
                </div>
                <button className="btn sm" disabled={!!fix} onClick={() => onFix(l)} aria-label={`Fix the line${m ? ` at ${clockText(m, true)}` : ''}`}>
                  Fix
                </button>
                <div className="meta-l">
                  <span className="num">{firstWord ? 'model first text word' : 'model reply'} {(ms / 1000).toFixed(2)} s</span>
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
