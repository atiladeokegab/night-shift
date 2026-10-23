import { clockText } from '../moment'
import type { Line, Moment } from '../types'

interface Props {
  lines: Line[] // newest first
  moments: Moment[]
}

// The line log (docs/design.md): every line so far, newest first, with its clock and first-word time.
export function LineLog({ lines, moments }: Props) {
  return (
    <section className="panel lines" aria-label="Lines">
      <h2>Lines</h2>
      {lines.length === 0 ? (
        <p className="muted">Lines appear here as Touchline calls them.</p>
      ) : (
        <ol>
          {lines.map((l) => {
            const m = moments.find((x) => x.idx === l.moment_idx)
            const ms = l.first_word_ms ?? l.latency_ms
            return (
              <li key={l.line_id}>
                <span className="when">{m ? clockText(m, true) : ''}</span>
                <span className="said">{l.text}</span>
                <span className="first-word">first word {(ms / 1000).toFixed(2)} s</span>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
