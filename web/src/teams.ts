import type { Match } from './types'

// Team chips and stickmen colours from docs/design.md ("Colour"); any other team gets a neutral chip.
const KNOWN: [string, string, string][] = [
  ['Spain', 'ESP', '#E8414C'],
  ['England', 'ENG', '#F4F4F4'],
  ['India', 'IND', '#4FA3FF'],
  ['Pakistan', 'PAK', '#2FBF71'],
]
const OTHER = ['#C9D2E3', '#8FA3C7']

export interface TeamStyle {
  name: string
  code: string
  color: string
}

// StatsBomb names women's sides "Spain Women's"; the chip and colour follow the country.
export function teamStyle(name: string, fallback = 0): TeamStyle {
  const hit = KNOWN.find(([country]) => name.startsWith(country))
  if (hit) return { name, code: hit[1], color: hit[2] }
  return { name, code: name.replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase() || '—', color: OTHER[fallback % 2] }
}

// [home, away]: from the match when the server names them, else from data/'s title "Home v Away, ...".
export function matchTeams(match: Match): [TeamStyle, TeamStyle] {
  const [home, away] = match.home && match.away
    ? [match.home, match.away]
    : (match.title ?? '').split(',')[0].split(' v ').map((s) => s.trim())
  return [teamStyle(home ?? 'Home', 0), teamStyle(away ?? 'Away', 1)]
}

// The side a moment's team plays for; in cricket the moment's team is the batting side.
export function sides(match: Match, team: string): { ours: TeamStyle; theirs: TeamStyle } {
  const [home, away] = matchTeams(match)
  return team === away.name ? { ours: away, theirs: home } : { ours: home, theirs: away }
}

// The two demo matches' card copy, exactly as docs/design.md ("Copy") gives it.
export const CARD_COPY: Record<string, { title: string; detail: string; result: string }> = {
  '3906390': {
    title: 'Spain v England',
    detail: "2023 Women's World Cup final · Sydney · 20 Aug 2023",
    result: 'Spain 1–0 England',
  },
  '1298150': {
    title: 'India v Pakistan',
    detail: 'T20 World Cup · MCG, Melbourne · 23 Oct 2022',
    result: 'India won by 4 wickets, off the last ball',
  },
}
