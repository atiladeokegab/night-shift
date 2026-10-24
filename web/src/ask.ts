import { clockText } from './moment.ts'
import type { Answer, Line, Moment } from './types'

// The calm copy for any failed question (#108): the provider's error or an HTTP status never reaches the page.
export const OFF_AIR = 'Commentator is off air for a moment'

export const offAir = (question: string, moment_idx: number): Answer => ({
  line_id: `off-air-${Date.now()}`, moment_idx, question, text: OFF_AIR, off_air: true,
})

// A 429 from the live site's budget guard (#244) carries a message for the viewer: thrown as this
// when a replay can't start, shown as the off-air answer when a question can't be asked.
export class Refused extends Error {}

export async function refused(res: Response): Promise<string | null> {
  if (res.status !== 429) return null
  try {
    return ((await res.json()) as { detail?: string }).detail ?? null
  } catch {
    return null
  }
}

export type LogItem = { line: Line; answer?: undefined } | { answer: Answer; line?: undefined }

// The Lines card's rows, newest first: each answer sits above the lines up to the moment it was asked at,
// so it reads in the match's order whatever the order the lines arrived in.
export function withAnswers(lines: Line[], answers: Answer[]): LogItem[] {
  const asked = [...answers].sort((a, b) => b.moment_idx - a.moment_idx) // stable: newest first within a moment
  const out: LogItem[] = []
  let i = 0
  for (const line of lines) {
    while (i < asked.length && asked[i].moment_idx >= line.moment_idx) out.push({ answer: asked[i++] })
    out.push({ line })
  }
  return [...out, ...asked.slice(i).map((answer) => ({ answer }))]
}

// An answer is about the moment it was asked at: "at 104:30", and stale once a later key moment is on
// screen, so it never reads as now after the match moved on. `moments` are the ones the picture reached.
export const answeredAt = (a: Pick<Answer, 'moment_idx' | 'asked_moment'>, moments: Moment[]): string | null => {
  if (a.asked_moment) return `at ${clockText(a.asked_moment)}`
  // A cold-open Stat and the first mapped event can share an idx. `moments` are already the
  // moments the picture has reached, in replay order, so use the latest visible one at that idx.
  const m = moments.filter((x) => x.idx === a.moment_idx).at(-1)
  return m ? `at ${clockText(m)}` : null
}
export const isStale = (a: Pick<Answer, 'moment_idx'>, moments: Pick<Moment, 'idx'>[]): boolean =>
  moments.some((m) => m.idx > a.moment_idx)

// One question at one moment is asked once (#186): the page's own quiet-spell "Where are we?" and a
// viewer's press a moment later would give two identical rows. `asking` is the key in flight. An
// off-air answer doesn't count, so asking again can still get one.
export const askKey = (question: string, momentIdx: number): string => `${momentIdx}|${question.trim().toLowerCase()}`
export const isRepeat = (answers: Answer[], asking: string | null, question: string, momentIdx: number): boolean => {
  const key = askKey(question, momentIdx)
  return asking === key || answers.some((a) => !a.off_air && askKey(a.question, a.moment_idx) === key)
}
