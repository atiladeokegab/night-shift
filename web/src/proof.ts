import type { Autonomy, Stats, TaskAdapter } from './types'

// The Proof card's "Next adapter" figure: fixes since the latest adapter against the number Mubit needs.
// Past the target it says so, rather than "66 of 25".
export function nextAdapter(toward: number, needed: number): { value: string; note: string | null } {
  if (toward < needed) return { value: `${toward} of ${needed}`, note: null }
  return { value: 'Ready to train', note: `${toward} fixes recorded · ${needed} needed: enough for the next adapter` }
}

const NONE: Autonomy = { called: 0, first_time: 0, auto_fixed: 0, to_human: 0 }

// The Proof card's autonomy rows (#204): this match, then all matches, straight from /stats or the
// `stats` event. None before core reports them; a match with no calls yet counts zeros.
export function autonomyRows(stats: Pick<Stats, 'autonomy' | 'autonomy_by_match'>, matchId: string | null): [string, Autonomy][] {
  if (!stats.autonomy) return []
  const rows: [string, Autonomy][] = matchId ? [['This match', stats.autonomy_by_match?.[matchId] ?? NONE]] : []
  return [...rows, ['All matches', stats.autonomy]]
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
  const failed = a.target === null ? 'Failed' : `below ${a.target}% target`
  const verdict = a.passed === null ? (a.status === 'ready' ? 'verdict not recorded' : null) : a.passed ? 'Passed' : failed
  return [
    a.status === 'ready' ? null : a.status === 'training' ? 'training' : 'not trained',
    a.version === null ? null : `v${a.version}`,
    a.score === null ? null : `${a.score}%`,
    verdict,
    a.kept === null ? null : `${a.kept.toLocaleString()} kept`,
  ].filter(Boolean).join(', ') || 'ready'
}
