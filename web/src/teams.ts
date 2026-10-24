import type { Match, Moment, Sport, Voice } from './types'

// Team colours and crest ink from docs/design.md ("Tokens") and the mockup's crests; any other team
// gets a neutral one.
const KNOWN: [string, string, string, string][] = [
  ['Spain', 'ESP', '#C8102E', '#F1BF00'],
  ['England', 'ENG', '#F4F4F4', '#1B2A5A'],
  ['India', 'IND', '#2F7DE1', '#FFFFFF'],
  ['Pakistan', 'PAK', '#0F8A4C', '#FFFFFF'],
]
const OTHER: [string, string][] = [['#C9D2E3', '#0E1524'], ['#8FA3C7', '#0E1524']]

export interface TeamStyle {
  name: string
  code: string
  color: string // the team bar and crest
  ink: string // letters on the crest
}

// StatsBomb names women's sides "Spain Women's"; the code and colour follow the country.
export function teamStyle(name: string, fallback = 0): TeamStyle {
  const hit = KNOWN.find(([country]) => name.startsWith(country))
  if (hit) return { name, code: hit[1], color: hit[2], ink: hit[3] }
  const [color, ink] = OTHER[fallback % 2]
  // Clubs are known by their last word ("Los Angeles Lakers" -> LAK); countries by their name.
  const word = name.trim().split(/\s+/).at(-1) ?? ''
  return { name, code: word.replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase() || '—', color, ink }
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

// The cricket score bar: the batting side's runs/wickets, and the other side only once it has a total
// (the second innings), so a first innings never reads as "PAK 1/1 IND", one-all.
export function cricketScore(match: Match, moment: Moment | null, moments: Moment[]) {
  if (!moment) return { batting: matchTeams(match)[0], score: '0/0', fielding: null }
  const { ours, theirs } = sides(match, moment.team)
  const s = moment.score
  // The fielding side's total: their last first-innings moment, else the target less one.
  const first = moments.filter((m) => m.period === 1 && m.team === theirs.name).at(-1)?.score
  const total = first && 'runs' in first ? `${first.runs}/${first.wickets}`
    : 'runs' in s && s.target ? String(s.target - 1) : null
  return {
    batting: ours,
    score: 'runs' in s ? `${s.runs}/${s.wickets}` : '0/0',
    fielding: moment.period === 2 && total ? { team: theirs, total } : null,
  }
}

// Card copy: the two demo matches from docs/design.md ("Copy"), and the iconic ones by what they are
// remembered for, with names, dates and results from data/sample/. The design's "Highlights 4:56 · 4 key
// moments" is a mockup placeholder (data/video/ maps 15 and 32 moments), so it is left out: no unmeasured figures.
export const CARD_COPY: Record<string, { title: string; detail: string; result: string }> = {
  '3869685': {
    title: 'Messi v Mbappé',
    detail: '2022 World Cup final · Argentina v France · 18 Dec 2022',
    result: 'Argentina 3–3 France, Argentina win 4–2 on penalties',
  },
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
  '0020500591': {
    title: "Kobe's 81 v Toronto",
    detail: 'Lakers v Raptors · NBA regular season · 22 Jan 2006',
    result: 'Lakers 122–104 Raptors, Kobe Bryant 81 points',
  },
  '0049700088': {
    title: "Jordan's last shot",
    detail: '1998 NBA Finals, Game 6 · Jazz v Bulls · 14 Jun 1998',
    result: 'Bulls 87–86 Jazz',
  },
  '9558': {
    title: 'Hamilton at Silverstone',
    detail: '2024 British Grand Prix · 7 Jul 2024',
    result: 'Hamilton wins by 1.5 s from Verstappen, Norris third',
  },
}

// The design's short voice name ("British", "Indian") from GET /voices' label
// ("Connor: British, energetic", "Viraj: Indian English, energetic") or a browser voice's ("British (browser)").
// A pick's label is the voice's own name ("British Football Announcer"), shown whole.
export function voiceName(v: Voice | null): string {
  if (!v) return ''
  if (!/[:(]/.test(v.label)) return v.label
  const desc = v.label.includes(':') ? v.label.split(':')[1] : v.label
  return desc.trim().split(/[\s,(]/)[0]
}

// "British commentator"; a pick's full name ("British Football Announcer") stands alone.
export function commentatorName(name: string): string {
  return name.includes(' ') ? name : `${name} commentator`
}

// The voice sheet's options for a sport: one per voice. Of the entries for the same voice (same_as), the
// sport's chosen one shows, else its default, else the first, so football's pick and f1's default are one option.
export function sheetVoices(voices: Voice[], sport: Sport, chosenId?: string): Voice[] {
  const rank = (v: Voice) => (v.id === chosenId ? 2 : v.default_for === sport ? 1 : 0)
  const one = new Map<string, Voice>()
  for (const v of voices) {
    const key = v.same_as ?? v.id
    const had = one.get(key)
    if (!had || rank(v) > rank(had)) one.set(key, v)
  }
  return [...one.values()]
}

export function defaultVoice(voices: Voice[], sport: Sport): Voice | null {
  return voices.find((v) => v.default_for === sport) ?? voices[0] ?? null
}
