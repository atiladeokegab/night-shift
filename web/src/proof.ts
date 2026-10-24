import type { Autonomy, LineCheck, LineCheckStats, Stats, TaskAdapter, VoiceHealth } from './types'

const NONE: Autonomy = { called: 0, first_time: 0, auto_fixed: 0, to_human: 0 }

// The Proof card's autonomy rows (#204): this match, then all matches, straight from /stats or the
// `stats` event. None before core reports them; a match with no calls yet counts zeros.
export function autonomyRows(stats: Pick<Stats, 'autonomy' | 'autonomy_by_match'>, matchId: string | null): [string, Autonomy][] {
  if (!stats.autonomy) return []
  const rows: [string, Autonomy][] = matchId ? [['This match', stats.autonomy_by_match?.[matchId] ?? NONE]] : []
  return [...rows, ['All matches', stats.autonomy]]
}

// A checked line's chip (#298): "Checker model: all ok" or the fields it calls wrong; none without a
// canonical reply, so a chip never claims a check that didn't happen.
export function checkText(c: LineCheck | undefined): string | null {
  if (!c?.labels) return null
  if (!c.wrong.length) return 'Checker model: all ok'
  return `Checker model: ${c.wrong.map((f) => f.replace('_', ' ')).join(', ')} may be wrong`
}

export const FALLBACK_NOTE = 'Voice: browser fallback (ElevenLabs unavailable)'

// The Proof card's voice row (#306): the server's last ElevenLabs failure, or the page's own fallback;
// null while ElevenLabs speaks the lines. A browser voice the viewer picked is no fallback.
export function voiceRow(v: VoiceHealth | undefined, fellBack: boolean): string | null {
  if (v?.provider !== 'browser' && !fellBack) return null
  const why = v?.provider === 'browser' && v.last_error ? ` · ${v.last_error.replaceAll('_', ' ')}` : ''
  const since = v?.provider === 'browser' && v.since ? ` since ${v.since.slice(11, 16)} UTC` : ''
  return FALLBACK_NOTE + why + since
}

// The Proof card's Line check row (#298), straight from /stats.
export function linecheckRow(s: LineCheckStats): string {
  return `${s.checked} checked · ${s.flags} flagged (${s.rules_missed} the rules missed) · ${s.fixes_sent} fixes sent to it`
}

const TASKS: [string, string][] = [['commentary', 'Commentary'], ['where_are_we', 'Where are we?'], ['line_check', 'Line check']]

// The Proof card's row per Mubit task (#209) in the console's words, e.g. "Line check: v1, 82%, Passed"
// or "v1, 55.8%, below 95% target", from only what the task's latest record says. No record, or a
// ready one without Mubit's verdict, reads "not recorded".
// None before core reports `adapters`.
export function adapterRows(adapters: Record<string, TaskAdapter> | undefined): string[] {
  if (!adapters) return []
  return TASKS.map(([task, label]) => `${label}: ${adapterRow(adapters[task])}`)
}

function adapterRow(a: TaskAdapter | undefined): string {
  if (!a) return 'not recorded'
  // the console's own wording only where the record shows it: a score under its target; else its verdict
  const failed = a.score !== null && a.target !== null && a.score < a.target ? `below ${a.target}% target` : 'Failed'
  const verdict = a.passed === null ? (a.state === 'testing' ? 'verdict not recorded' : null) : a.passed ? 'Passed' : failed
  return [
    a.state === 'collecting' ? 'collecting' : null,
    a.version === null ? null : `v${a.version}`,
    a.score === null ? null : `${a.score}%`,
    verdict,
    a.kept === null ? null : `${a.kept.toLocaleString()} kept`,
  ].filter(Boolean).join(', ')
}

// The fix counts' heading: "Training" alone read as training under way; these are recorded data.
export const TRAINING_LABEL = 'Training data'

// The Adapter row's green dot: only a recorded pass of Mubit's gate, never one inferred from a status.
export const adapterGood = (stats: Pick<Stats, 'adapter'>): boolean => stats.adapter?.state === 'passed'
