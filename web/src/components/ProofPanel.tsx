import { useEffect, useState } from 'react'
import { getStats } from '../api'
import type { Adapter, Stats } from '../types'
import { SideBySide } from './SideBySide'

interface Props {
  live: Stats | null // the latest `stats` event from the replay, newer than the first GET /stats
}

// The Proof card (docs/design.md): the model's first-text-word latency, cost per line, lines, fixes and
// the adapter, all from GET /stats, then updated with every `stats` event. Nothing here is computed in
// the browser. The labels name what is measured (#37 review), not the mockup's "first word".
export function ProofPanel({ live }: Props) {
  const [fetched, setFetched] = useState<Stats | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    getStats().then(setFetched, () => setFailed(true))
  }, [])

  const stats = live ?? fetched
  let body
  if (!stats && failed) body = <p className="err-text">Stats unavailable. Lines still play.</p>
  else if (!stats) body = <p className="hint" role="status">Loading stats…</p>
  else {
    const empty = stats.lines === 0
    const v = (x: string) => (empty ? '–' : x)
    const adapter = stats.adapter
    body = (
      <>
        <dl className="stats">
          <Figure label="Model first text word p50" value={v(seconds(stats.first_word_ms_p50))} />
          <Figure label="Model first text word p95" value={v(seconds(stats.first_word_ms_p95))} />
          <Figure label="Cost per line" value={v(dollars(stats.cost_per_line_usd))} />
          <Figure label="Lines" value={v(String(stats.lines))} />
          <Figure label="Fixes" value={v(String(stats.fixes))} />
          <div className="wide">
            <dt className="label">Adapter</dt>
            <dd className={adapter?.status === 'ready' ? 'good' : undefined}>{adapterText(adapter)}</dd>
          </div>
          {adapter && !adapter.cost_measurable && (
            <div className="wide">
              <dt className="label">Adapter cost</dt>
              <dd>Not measurable. <span className="hint">Mubit doesn't report the adapter's cost to the app.</span></dd>
            </div>
          )}
        </dl>
        {empty && <p className="small">No lines yet.</p>}
      </>
    )
  }
  return (
    <>
      <section className="panel glass" aria-label="Proof" aria-live="polite">
        <div className="panel-h"><h3>Proof</h3></div>
        {body}
        <p className="small">
          Model first text word: time from the moment to the first word of the model's text reply, measured through
          Mubit. Finishing the line, speech synthesis and playback are not included.
        </p>
      </section>
      <SideBySide />
    </>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  )
}

// The design's adapter states; "–" until core reports the adapter.
function adapterText(adapter?: Adapter | null): string {
  if (adapter?.status === 'not_trained') return 'Not trained yet. Mubit trains it on our calls and producer fixes.'
  if (adapter?.status === 'training') return 'Training: Mubit is building the adapter.'
  if (adapter?.status === 'ready' && adapter.agree !== null && adapter.total !== null) {
    return `Agrees with the big model on ${adapter.agree} of ${adapter.total} test moments.`
  }
  return '–'
}

function seconds(ms: number | null): string {
  return ms === null ? '–' : `${(ms / 1000).toFixed(2)} s`
}

function dollars(usd: number | null | undefined): string {
  return usd === null || usd === undefined ? '–' : `$${usd.toFixed(4)}`
}
