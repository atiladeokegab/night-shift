import type { Autonomy, Stats, TaskAdapter } from './types'

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

// The Adapter row's green dot: only a recorded pass of Mubit's gate, never one inferred from a status.
export const adapterGood = (stats: Pick<Stats, 'adapter'>): boolean => stats.adapter?.state === 'passed'
