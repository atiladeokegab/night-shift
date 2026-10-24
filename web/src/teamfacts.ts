import type { TeamGame } from './types.ts'

const WORD: Record<string, string> = { W: 'won', D: 'drew', L: 'lost' }

// "Orlando Pride: won 3 of their last 5" (#375): short enough to say aloud.
export function formLine(team: string, form: TeamGame[]): string {
  if (!form.length) return `${team}: no recent games on record`
  const parts = Object.entries(WORD)
    .map(([code, word]) => [word, form.filter((g) => g.result === code).length] as const)
    .filter(([, n]) => n > 0)
    .map(([word, n]) => `${word} ${n}`)
  return `${team}: ${parts.length ? parts.join(', ') : 'played'} of their last ${form.length}`
}

// "Won 2-1 at home against Everton, 20 April 2016"
export function gameLine(g: TeamGame): string {
  const day = new Date(`${g.date}T00:00:00Z`)
  const when = Number.isNaN(day.getTime()) ? g.date : day.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
  const word = WORD[g.result] ?? g.result
  return `${word.charAt(0).toUpperCase()}${word.slice(1)} ${g.score} ${g.home ? 'at home' : 'away'} against ${g.opponent}, ${when}`
}
