// data/side_by_side.json's shape (eval/side_by_side.py) and what the "Big model vs ours" panel shows from it.

export interface Line {
  text: string
  model: string
  first_word_ms: number | null
  latency_ms: number | null
  cost_usd: number | null
}

export interface Pair {
  sport: string
  match_id: string
  match: string
  moment_idx: number
  clock: string | null
  moment: string
  big: Line
  adapter: Line | null
  verdict: string
}

export interface Report {
  recorded_on: string
  big_model: string
  adapter: { name: string | null; status: string; adapters: number; best_match_pct: number; callable: boolean; why: string }
  pairs: Pair[]
}

export interface View {
  paired: boolean // at least one recorded adapter line: show both lines side by side
  bigCost: number | null // mean $ per line
  oursCost: number | null // null until an adapter line with a cost is recorded
  ours: string // our commentator's state: the recorded status once paired, else that no version has passed
}

function mean(xs: (number | null)[]): number | null {
  const known = xs.filter((x): x is number => x !== null)
  return known.length ? known.reduce((a, b) => a + b, 0) / known.length : null
}

export function viewOf(report: Report): View {
  const ours = report.pairs.flatMap((p) => (p.adapter ? [p.adapter] : []))
  return {
    paired: ours.length > 0,
    bigCost: mean(report.pairs.map((p) => p.big.cost_usd)),
    oursCost: mean(ours.map((l) => l.cost_usd)),
    // what's recorded, never that training is under way
    ours: ours.length ? report.adapter.status : "no version has passed Mubit's test yet",
  }
}
