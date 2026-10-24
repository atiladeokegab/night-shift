import type { Autonomy, Stats } from './types'

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
