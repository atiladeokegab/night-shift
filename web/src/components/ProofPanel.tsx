import { useEffect, useState } from 'react'
import { getStats } from '../api'
import type { Adapter, Stats } from '../types'

interface Props {
  live: Stats | null // the latest `stats` event from the replay, newer than the first GET /stats
}

// The proof panel (docs/design.md): first-word latency, cost per line, lines, fixes and the adapter,
// all from GET /stats, then updated with every `stats` event. Nothing here is computed in the browser.
export function ProofPanel({ live }: Props) {
  const [fetched, setFetched] = useState<Stats | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getStats().then(setFetched, () => setFailed(true))
  }, [])

  const stats = live ?? fetched
  return (
    <section className="panel proof" aria-label="Proof">
      <h2>Proof</h2>
      {!stats && failed ? (
        <p className="muted">Stats unavailable. Lines still play.</p>
      ) : !stats ? (
        <p className="muted">Loading stats…</p>
      ) : (
        <>
          {stats.lines === 0 && <p className="muted">No lines yet.</p>}
          <dl>
            <Figure label="First word p50" value={seconds(stats.first_word_ms_p50)} />
            <Figure label="First word p95" value={seconds(stats.first_word_ms_p95)} />
            <Figure label="Cost per line" value={dollars(stats.cost_per_line_usd)} />
            <Figure label="Lines" value={stats.lines ? String(stats.lines) : '–'} />
            <Figure label="Fixes" value={stats.lines ? String(stats.fixes) : '–'} />
          </dl>
          <AdapterResult adapter={stats.adapter} />
        </>
      )}
      <p className="footnote">First word: time from the moment to the first spoken word. Measured through Mubit.</p>
    </section>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

// The design's adapter states; "–" until core reports the adapter (#29).
function AdapterResult({ adapter }: { adapter?: Adapter | null }) {
  let text = '–'
  if (adapter?.status === 'not_trained') text = `Not trained yet: needs ${adapter.needed} kept lines (${adapter.kept} so far).`
  if (adapter?.status === 'training') text = 'Training: Mubit is building the adapter.'
  if (adapter?.status === 'ready' && adapter.agree !== null && adapter.total !== null) {
    text = `Agrees with the big model on ${adapter.agree} of ${adapter.total} test moments.`
  }
  return (
    <div className="adapter">
      <span className="label">Adapter</span>
      <p className="result">{text}</p>
      {adapter && !adapter.cost_measurable && (
        <p className="muted">Cost: Not measurable. Mubit doesn't report the adapter's cost to the app.</p>
      )}
    </div>
  )
}

function seconds(ms: number | null): string {
  return ms === null ? '–' : `${(ms / 1000).toFixed(2)} s`
}

function dollars(usd: number | null | undefined): string {
  return usd === null || usd === undefined ? '–' : `$${usd.toFixed(4)}`
}
