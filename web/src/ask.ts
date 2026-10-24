import type { Answer, Line } from './types'

// The calm copy for any failed question (#108): the provider's error or an HTTP status never reaches the page.
export const OFF_AIR = 'Commentator is off air for a moment'

export const offAir = (question: string, moment_idx: number): Answer => ({
  line_id: `off-air-${Date.now()}`, moment_idx, question, text: OFF_AIR, off_air: true,
})

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
