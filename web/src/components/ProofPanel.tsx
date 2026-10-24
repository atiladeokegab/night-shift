import { useEffect, useState, type ReactNode } from 'react'
import { getReview, getStats } from '../api'
import type { Adapter, Autonomy, SpeakerStats, Stats } from '../types'
import { SideBySide } from './SideBySide'
import { adapterGood, adapterRows, autonomyRows, consoleRow, FLAG_NOTE, heldoutRow, linecheckRow, TRAINING_LABEL, voiceRow } from '../proof'

interface Props {
  live: Stats | null // the latest `stats` event from the replay, newer than the first GET /stats
  matchId?: string // the match on screen: its own autonomy row first (#204)
  fellBack?: boolean // the page is reading lines in browser speech (#306)
}

// The Proof card (docs/design.md): the model's first-text-word latency, cost per line, lines, fixes and
// the adapter, all from GET /stats, then updated with every `stats` event. Nothing here is computed in
// the browser. "First word" is the model's first text word; the footnote says what it measures (#37, #154).
export function ProofPanel({ live, matchId, fellBack = false }: Props) {
  const [fetched, setFetched] = useState<Stats | null>(null)
  const [failed, setFailed] = useState(false)
  const [flagged, setFlagged] = useState<number | null>(null) // stored lines the number check flags (#171)

  useEffect(() => {
    getStats().then(setFetched, () => setFailed(true))
    getReview().then((xs) => setFlagged(xs.length), () => {}) // no count is shown rather than a wrong one
  }, [])
  useEffect(() => {
    if (fellBack) getStats().then(setFetched, () => {}) // why it fell back: only GET /stats says
  }, [fellBack])

  const stats = live ?? fetched
  let body
  if (!stats && failed) body = <p className="err-text">Stats unavailable. Lines still play.</p>
  else if (!stats) body = <p className="hint" role="status">Loading stats…</p>
  else {
    const empty = stats.lines === 0
    const adapter = stats.adapter
    const tasks = adapterRows(stats.adapters, stats.scorecheck)
    const voice = voiceRow(live?.voice ?? fetched?.voice, fellBack)
    const heldout = heldoutRow(stats.linecheck?.heldout)
    const mubit = consoleRow(adapter?.console)
    // the lead's calls (Haiku) and the analyst's stat lines (Sonnet) apart, so neither skews the other
    const groups: [string, SpeakerStats][] = stats.by_speaker
      ? [['Lead', stats.by_speaker.lead], ['Analyst', stats.by_speaker.analyst]]
      : [['All lines', { ...stats, model: '', cost_per_line_usd: stats.cost_per_line_usd ?? null }]]
    body = (
      <>
        <dl className="stats">
          {voice && (
            <div className="wide">
              <dt className="label">Voice</dt>
              <dd>{voice}</dd>
            </div>
          )}
          {/* first: how many calls the number check passed, the retry fixed, or a person must (#204) */}
          {autonomyRows(stats, matchId ?? null).map(([name, a]) => <Calls key={name} name={name} a={a} />)}
          {stats.matches_measured !== undefined && <PerMatch stats={stats} />}
          {groups.map(([name, s]) => <Speaker key={name} name={name} s={s} />)}
          {/* own heading so the fix counts don't read as the analyst's */}
          <div className="wide">
            <dt className="label">{TRAINING_LABEL}</dt>
            <dd>Your fixes that passed the check, recorded in Mubit as training data</dd>
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
          {/* a second model on every live lead line (#298): what it flagged, and the fixes that teach it */}
          {stats.linecheck && (
            <div className="wide">
              <dt className="label">Checker model</dt>
              <dd>{linecheckRow(stats.linecheck)}</dd>
              {/* nothing until eval/linecheck_heldout.json is committed (#317) */}
              {heldout && <dd>{heldout}</dd>}
              {heldout && <dd className="small">{FLAG_NOTE}</dd>}
            </div>
          )}
          {stats.fixes_toward_next !== undefined && (
            <Figure className="two" label="Since adapter record" value={String(stats.fixes_toward_next)} />
          )}
          <div className="wide">
            <dt className="label">Adapter</dt>
            <dd className={adapterGood(stats) ? 'good' : undefined}>{adapterText(adapter)}</dd>
            {/* the console's own counts, read by hand on a stated day (#317): never live */}
            {mubit && <dd className="small">{mubit}</dd>}
          </div>
          {/* each Mubit task's latest version, as recorded from Mubit's console (#209) */}
          {!!tasks.length && (
            <div className="wide">
              <dt className="label">Mubit tasks</dt>
              {tasks.map((row) => <dd key={row}>{row}</dd>)}
            </div>
          )}
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

// each model id on one line (.nw): never "claude-sonnet-5-" / "5"
const ids = (list: string) => list.split(', ').filter(Boolean).map((id, i) => <span key={id}>{i > 0 && ', '}<span className="nw">{id}</span></span>)

function Speaker({ name, s }: { name: string; s: SpeakerStats }) {
  const all = !!s.served_lines && s.served_lines === s.lines
  const v = (x: string) => (s.lines === 0 ? '–' : x)
  return (
    <>
      <div className="wide">
        <dt className="label">{name}</dt>
        <dd>
          {/* "Served by" alone only when every line says what served it (#250): older lines don't */}
          {all ? <>Served by {ids(s.served_by!)}</> : ids(s.model)}
          {!all && !!s.served_lines && <> · served by {ids(s.served_by!)} on {s.served_lines.toLocaleString()} lines</>}
          {(all || s.model) && ' · '}{`${s.lines.toLocaleString()} lines · all matches`}
        </dd>
      </div>
      {/* one "First word" caption over both, so each label fits one line at 1280 px; "Cost" over its own */}
      <div className="cap" aria-hidden="true"><dt className="label">First word</dt></div>
      <div className="cap cost" aria-hidden="true"><dt className="label">Cost</dt></div>
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

// The adapter as its latest record says it, in core's words; "–" until core reports the adapter.
function adapterText(adapter?: Adapter | null): string {
  return adapter?.summary ?? '–'
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
