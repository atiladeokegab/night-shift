import { clockText } from '../moment'
import type { Line, Moment } from '../types'

interface Props {
  lines: Line[] // newest first
  late: string[] // released after the video had moved past them: never shown or spoken
  moments: Moment[]
}

// The line log (docs/design.md): every line so far, newest first, with its clock and the model's
// first-word time (time to its first word of text; video wait and speech come after).
export function LineLog({ lines, late, moments }: Props) {
  return (
    <section className="panel lines" aria-label="Lines">
      <h2>Lines</h2>
      {lines.length === 0 ? (
        <p className="muted">Lines appear here as Touchline calls them.</p>
      ) : (
        <ol>
          {lines.map((l) => {
            const m = moments.find((x) => x.idx === l.moment_idx)
            const firstWord = l.first_word_ms !== undefined
            const ms = l.first_word_ms ?? l.latency_ms
            return (
              <li key={l.line_id} className={late.includes(l.line_id) ? 'late' : undefined}>
                <span className="when">{m ? clockText(m, true) : ''}</span>
                <span className="said">{l.text}</span>
                <span className="first-word">
                  {late.includes(l.line_id) ? 'not spoken: the video had moved past it · ' : ''}
                  {/* first_word_ms is the model's first text word, not the spoken word; latency_ms the whole reply (#37 review). */}
                  {firstWord ? 'model first text word' : 'model reply'} {(ms / 1000).toFixed(2)} s
                </span>
                {/* The fix sheet arrives with the fix loop (#16). */}
                <button className="fix" disabled title="Fixing lines arrives with the fix loop (#16)">Fix</button>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
