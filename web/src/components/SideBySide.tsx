// The repo's data/, read at build time: eval/side_by_side.py writes it offline, so every line here is recorded.
import raw from '../../../data/side_by_side.json?raw'

interface Line {
  text: string
  model: string
  first_word_ms: number | null
  latency_ms: number | null
  cost_usd: number | null
}

interface Pair {
  sport: string
  match_id: string
  match: string
  moment_idx: number
  clock: string | null
  moment: string
  big: Line
  adapter: Line | null
  verdict: string
}

interface Report {
  recorded_on: string
  big_model: string
  adapter: { name: string | null; status: string; adapters: number; best_match_pct: number; callable: boolean; why: string }
  pairs: Pair[]
}

const report = JSON.parse(raw) as Report

// "Big model vs ours" (#141): held-out moments, the big model's recorded line beside the adapter's. The app can't
// call the adapter (eval/side_by_side.py says why), so its side says so; nothing here claims the two agree.
export function SideBySide() {
  const { adapter, pairs } = report
  const name = adapter.name ? `adapter ${adapter.name}` : `best of ${adapter.adapters} adapters`
  return (
    <section className="panel glass" aria-label="Big model vs ours">
      <div className="panel-h">
        <h3>Big model vs ours</h3>
        <span className="badge">Recorded</span>
      </div>
      <p className="hint">
        Recorded on {date(report.recorded_on)}; big model {report.big_model}; {name}, {adapter.best_match_pct}%
        agreement (matched the big model's answers on Mubit's test): <strong>{adapter.status}</strong>. Moments from
        held-out matches the adapter never trained on.
      </p>
      <ol style={{ listStyle: 'none', padding: 0, margin: '14px 0 0', display: 'grid', gap: 14 }}>
        {pairs.map((p) => (
          <li key={`${p.sport}-${p.match_id}-${p.moment_idx}`} style={{ borderTop: '1px solid var(--line)', paddingTop: 12 }}>
            <p className="label" style={{ margin: '0 0 8px', lineHeight: 1.4 }}>
              {p.match}{p.clock ? ` · ${p.clock}` : ''} · {p.moment}
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
              <Side who="Big model" line={p.big} />
              <Side who="Ours" line={p.adapter} verdict={p.verdict} />
            </div>
          </li>
        ))}
      </ol>
      {!adapter.callable && <p className="small">No adapter line: {adapter.why}.</p>}
    </section>
  )
}

function Side({ who, line, verdict }: { who: string; line: Line | null; verdict?: string }) {
  return (
    <div>
      <p className="small" style={{ margin: 0 }}>{who}</p>
      <p style={{ margin: '4px 0', fontSize: '.92rem', color: line ? 'var(--fg)' : 'var(--faint)' }}>
        {line ? `“${line.text}”` : 'No line'}
      </p>
      {line && (
        <p className="small num" style={{ margin: 0 }}>
          {ms(line.first_word_ms)} first word · {ms(line.latency_ms)} total · {dollars(line.cost_usd)}
        </p>
      )}
      {verdict && <p className="small" style={{ margin: '4px 0 0' }}>{verdict}</p>}
    </div>
  )
}

function ms(x: number | null): string {
  return x === null ? '–' : `${Math.round(x)} ms`
}

function dollars(usd: number | null): string {
  return usd === null ? '–' : `$${usd.toFixed(4)}`
}

function date(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}
