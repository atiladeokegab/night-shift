// The repo's data/, read at build time: eval/side_by_side.py writes it offline, so every line here is recorded.
import data from '../../../data/side_by_side.json' with { type: 'json' }
import { viewOf, type Line, type Report } from '../sideBySide'

const report = data as Report

// "Big model vs ours" (#141) on held-out moments. Until Mubit serves a passing adapter version there is no
// line of ours to show, so the big model's recorded lines stand as the baseline it must match; once a pair
// carries an adapter line, both show side by side. Nothing here claims the two agree beyond the data.
export function SideBySide() {
  const { adapter, pairs } = report
  const view = viewOf(report)
  return (
    <section className="panel glass" aria-label="Big model vs ours" style={{ marginTop: 16 }}>
      <div className="panel-h">
        <h2>Big model vs ours</h2>
        <span className="badge">Recorded</span>
      </div>
      {!view.paired && (
        <p style={{ margin: '0 0 8px', font: '500 1rem/1.35 var(--display)', color: 'var(--fg)' }}>
          Our model isn't ready yet. Here's the big model it has to match.
        </p>
      )}
      <p className="hint">
        <strong>Our commentator: {view.ours}.</strong> {adapter.adapters}{' '}
        adapters on Mubit's console at 00:14 UTC on 25 Oct, best commentary task {adapter.best_match_pct}% on its
        test{view.paired ? ` (${adapter.status}).` : '; the app does not call an adapter.'}
      </p>
      <Costs big={view.bigCost} ours={view.oursCost} />
      <p className="small" style={{ margin: '16px 0 0' }}>
        {view.paired ? 'Both lines · ' : ''}{report.big_model} · recorded {date(report.recorded_on)}, held-out moments
      </p>
      <ol style={{ listStyle: 'none', padding: 0, margin: '10px 0 0', display: 'grid', gap: 12 }}>
        {pairs.map((p) => (
          <li key={`${p.sport}-${p.match_id}-${p.moment_idx}`} style={{ borderTop: '1px solid var(--line)', paddingTop: 10 }}>
            <p className="small" style={{ margin: '0 0 4px' }}>
              {p.match}{p.clock ? ` · ${p.clock}` : ''} · {p.moment}
            </p>
            {p.adapter ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
                <Said who="Big model" line={p.big} />
                <Said who="Ours" line={p.adapter} verdict={p.verdict} />
              </div>
            ) : (
              <Said line={p.big} />
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}

function Costs({ big, ours }: { big: number | null; ours: number | null }) {
  const width = (x: number | null) => (x === null || !big ? 0 : Math.min(100, (x / big) * 100))
  const row = (who: string, x: number | null, idle: string) => (
    <div style={{ display: 'grid', gridTemplateColumns: '72px 1fr auto', alignItems: 'center', gap: 10 }}>
      <span className="small" style={{ margin: 0 }}>{who}</span>
      {x === null ? (
        <span className="small" style={{ margin: 0, border: '1px dashed var(--line-hi)', borderRadius: 6, padding: '1px 8px', textAlign: 'center' }}>
          {idle}
        </span>
      ) : (
        <span style={{ height: 8, borderRadius: 4, border: '1px solid var(--line-hi)', overflow: 'hidden' }}>
          <span style={{ display: 'block', height: '100%', width: `${width(x)}%`, background: 'var(--amber)' }} />
        </span>
      )}
      <span className="small num" style={{ margin: 0 }}>{x === null ? 'not yet measured' : `${dollars(x)}/line`}</span>
    </div>
  )
  return (
    <div style={{ display: 'grid', gap: 6, marginTop: 14 }} aria-label="Cost per line">
      {row('Big model', big, 'not recorded')}
      {row('Ours', ours, 'not served')}
    </div>
  )
}

function Said({ who, line, verdict }: { who?: string; line: Line; verdict?: string }) {
  return (
    <div>
      {who && <p className="small" style={{ margin: 0 }}>{who}</p>}
      <p style={{ margin: '2px 0 4px', fontSize: '.92rem', color: 'var(--fg)' }}>“{line.text}”</p>
      <p className="small num" style={{ margin: 0 }}>
        {ms(line.first_word_ms)} first word · {ms(line.latency_ms)} total · {dollars(line.cost_usd)}
      </p>
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
