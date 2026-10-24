import { useEffect, useState, type ReactNode } from 'react'
import { getReview, getStats } from '../api'
import type { Adapter, Autonomy, SpeakerStats, Stats } from '../types'
import { SideBySide } from './SideBySide'
import { autonomyRows, nextAdapter } from '../proof'

interface Props {
  live: Stats | null // the latest `stats` event from the replay, newer than the first GET /stats
  matchId?: string // the match on screen: its own autonomy row first (#204)
}

// The Proof card (docs/design.md): the model's first-text-word latency, cost per line, lines, fixes and
// the adapter, all from GET /stats, then updated with every `stats` event. Nothing here is computed in
// the browser. "First word" is the model's first text word; the footnote says what it measures (#37, #154).
export function ProofPanel({ live, matchId }: Props) {
  const [fetched, setFetched] = useState<Stats | null>(null)
  const [failed, setFailed] = useState(false)
  const [flagged, setFlagged] = useState<number | null>(null) // stored lines the number check flags (#171)

  useEffect(() => {
    getStats().then(setFetched, () => setFailed(true))
    getReview().then((xs) => setFlagged(xs.length), () => {}) // no count is shown rather than a wrong one
  }, [])

  const stats = live ?? fetched
  let body
  if (!stats && failed) body = <p className="err-text">Stats unavailable. Lines still play.</p>
  else if (!stats) body = <p className="hint" role="status">Loading stats…</p>
  else {
    const empty = stats.lines === 0
    const adapter = stats.adapter
    const next = nextAdapter(stats.fixes_toward_next ?? 0, adapter?.needed ?? 25)
    // the lead's calls (Haiku) and the analyst's stat lines (Sonnet) apart, so neither skews the other
    const groups: [string, SpeakerStats][] = stats.by_speaker
      ? [['Lead', stats.by_speaker.lead], ['Analyst', stats.by_speaker.analyst]]
      : [['All lines', { ...stats, model: '', cost_per_line_usd: stats.cost_per_line_usd ?? null }]]
    body = (
      <>
        <dl className="stats">
          {/* first: how many calls the number check passed, the retry fixed, or a person must (#204) */}
          {autonomyRows(stats, matchId ?? null).map(([name, a]) => <Calls key={name} name={name} a={a} />)}
          {stats.matches_measured !== undefined && <PerMatch stats={stats} />}
          {groups.map(([name, s]) => <Speaker key={name} name={name} s={s} />)}
          {/* own heading so the fix counts don't read as the analyst's */}
          <div className="wide">
            <dt className="label">Training</dt>
            <dd>{next.note ?? 'Your fixes Mubit trains on'}</dd>
          </div>
          <Figure label="Fixes" value={String(stats.fixes_recorded ?? 0)} />
          {/* a moment with a producer's fix is said in the fixed words on every later replay (#232) */}
          {stats.spoken_from_fix !== undefined && <Figure label="Fixes heard" value={String(stats.spoken_from_fix)} />}
          {!!flagged && (
            <div className="wide">
              <dt className="label">To review</dt>
              <dd><a href="#review">{flagged} flagged line{flagged === 1 ? '' : 's'} to fix</a></dd>
            </div>
          )}
          {stats.fixes_toward_next !== undefined && (
            <Figure className="two" label="Next adapter" value={next.value} />
          )}
          <div className="wide">
            <dt className="label">Adapter</dt>
            <dd className={adapter?.status === 'ready' ? 'good' : undefined}>{adapterText(adapter)}</dd>
          </div>
        </dl>
        {empty && <p className="small">No lines yet.</p>}
      </>
    )
  }
  return (
    <>
      <section className="panel glass" aria-label="Proof">
        <div className="panel-h"><h3>Proof</h3></div>
        {body}
        <p className="small">
          First time: the call passed the number check. Auto-fixed: it failed, and the retry passed. To a human:
          the retry failed too, so a line built from the match data was said and the call waits in Review.
          First word: time from the match moment to the first word of the model's text reply, measured through
          Mubit. Finishing the line, speech synthesis and playback are not included.
          Per full replay: a replay from the first moment to the last, at list prices. Model: the tokens of
          every line it said, cached or not; Voice: its speech characters.
          {stats?.adapter && !stats.adapter.cost_measurable && " Adapter cost: not measurable; Mubit doesn't report it to the app."}
        </p>
      </section>
      <SideBySide />
    </>
  )
}

function Calls({ name, a }: { name: string; a: Autonomy }) {
  return (
    <>
      <div className="wide">
        <dt className="label">Calls · {name}</dt>
        <dd>{a.called.toLocaleString()} checked against the match data</dd>
      </div>
      <Figure className="third" label="First time" value={a.first_time.toLocaleString()} />
      <Figure className="third" label="Auto-fixed" value={a.auto_fixed.toLocaleString()} />
      <Figure className="third" label="To a human" value={a.to_human.toLocaleString()} />
    </>
  )
}

// what one full replay costs us, the model and the voice apart (#174)
function PerMatch({ stats }: { stats: Stats }) {
  const n = stats.matches_measured ?? 0
  return (
    <>
      <div className="wide">
        <dt className="label">Per full replay ({n} measured)</dt>
        <dd>{n ? 'Mean cost: Total = Model + Voice' : 'Shows once a match plays start to finish'}</dd>
      </div>
      <Figure className="third" label="Total" value={cents(stats.cost_per_match_usd)} />
      <Figure className="third" label="Model" value={cents(stats.model_cost_per_match_usd)} />
      <Figure className="third" label="Voice" value={cents(stats.voice_cost_per_match_usd)} />
    </>
  )
}

function Speaker({ name, s }: { name: string; s: SpeakerStats }) {
  const v = (x: string) => (s.lines === 0 ? '–' : x)
  return (
    <>
      <div className="wide">
        <dt className="label">{name}</dt>
        <dd>{[s.served_by ? `Served by ${s.served_by}` : s.model, `${s.lines.toLocaleString()} lines · all matches`].filter(Boolean).join(' · ')}</dd>
      </div>
      {/* one "First word" caption over both, so each label fits one line at 1280 px; "Cost" over its own */}
      <div className="cap" aria-hidden="true"><dt className="label">First word</dt></div>
      <div className="cap side" aria-hidden="true"><dt className="label">Cost</dt></div>
      <Figure className="third" label={<><span className="sr-only">First word </span>Median</>} value={v(seconds(s.first_word_ms_p50))} />
      <Figure className="third" label={<><span className="sr-only">First word </span>P95</>} value={v(seconds(s.first_word_ms_p95))} />
      <Figure className="third" label={<><span className="sr-only">Cost </span>Per line</>} value={v(dollars(s.cost_per_line_usd))} />
    </>
  )
}

function Figure({ label, value, className }: { label: ReactNode; value: string; className?: string }) {
  return (
    <div className={className}>
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

function cents(usd: number | null | undefined): string {
  return usd === null || usd === undefined ? '–' : `$${usd.toFixed(2)}`
}

function dollars(usd: number | null | undefined): string {
  return usd === null || usd === undefined ? '–' : `$${usd.toFixed(4)}`
}
