// The repo's data/, read at build time: eval/side_by_side.py writes it offline, so every line here is recorded.
import raw from '../../../data/side_by_side.json?raw'
import { viewOf, type Line, type Report } from '../sideBySide'

const report = JSON.parse(raw) as Report

// "Big model vs ours" (#141) on held-out moments. Until Mubit serves a passing adapter version there is no
// line of ours to show, so the big model's recorded lines stand as the baseline it must match; once a pair
// carries an adapter line, both show side by side. Nothing here claims the two agree beyond the data.
export function SideBySide() {
  const { adapter, pairs } = report
  const view = viewOf(report)
  return (
    <section className="panel glass" aria-label="Big model vs ours">
      <div className="panel-h">
        <h3>Big model vs ours</h3>
        <span className="badge">Recorded</span>
      </div>
      <p className="hint">
        <strong>Our commentator: {view.paired ? adapter.status : 'training on Mubit'}.</strong> {adapter.adapters}{' '}
        adapter versions so far, best {adapter.best_match_pct}% agreement with the big model
        {view.paired
          ? ` (Mubit's test: ${adapter.status}).`
          : "; not yet passing Mubit's test, so it isn't served. Lines appear here beside the big model's once a version passes."}
      </p>
      <Costs big={view.bigCost} ours={view.oursCost} />
      <p className="label" style={{ margin: '16px 0 0', lineHeight: 1.4 }}>
        {view.paired ? 'Both lines' : 'The baseline it must match'} · {report.big_model} · recorded{' '}
        {date(report.recorded_on)}, held-out moments
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
  const row = (who: string, x: number | null) => (
    <div style={{ display: 'grid', gridTemplateColumns: '72px 1fr auto', alignItems: 'center', gap: 10 }}>
      <span className="small" style={{ margin: 0 }}>{who}</span>
      <span style={{ height: 8, borderRadius: 4, border: '1px dashed var(--line-hi)', overflow: 'hidden' }}>
        <span style={{ display: 'block', height: '100%', width: `${width(x)}%`, background: 'var(--amber)' }} />
      </span>
      <span className="small num" style={{ margin: 0 }}>{x === null ? 'not yet measured' : `${dollars(x)}/line`}</span>
    </div>
  )
  return (
    <div style={{ display: 'grid', gap: 6, marginTop: 14 }} aria-label="Cost per line">
      {row('Big model', big)}
      {row('Ours', ours)}
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
