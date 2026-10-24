import { SPORTS, type Match, type Moment, type Sport, type Voice } from './types.ts'

// Team colours and crest ink from docs/design.md ("Tokens") and the mockup's crests; any other team
// gets a neutral one.
const KNOWN: [string, string, string, string][] = [
  ['Spain', 'ESP', '#C8102E', '#F1BF00'],
  ['England', 'ENG', '#F4F4F4', '#1B2A5A'],
  ['India', 'IND', '#2F7DE1', '#FFFFFF'],
  ['Pakistan', 'PAK', '#0F8A4C', '#FFFFFF'],
  ['Chelsea', 'CHE', '#034694', '#FFFFFF'],
  ['Tottenham', 'TOT', '#F4F4F4', '#132257'],
  ['Brighton', 'BHA', '#0057B8', '#FFFFFF'], // codes as on the broadcast's score bug
  ['Bristol City', 'BRI', '#E21A23', '#FFFFFF'],
  ['Verstappen', 'VER', '#3671C6', '#FFFFFF'], // Red Bull blue, 2024
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

// Card copy: the demo match from docs/design.md ("Copy"), and the iconic ones by what they are
// remembered for, with names, dates and results from data/sample/. The design's "Highlights 4:56 · 4 key
// moments" is a mockup placeholder (data/video/ maps 15 and 32 moments), so it is left out: no unmeasured figures.
export const CARD_COPY: Record<string, { title: string; detail: string; result: string; crest?: string; note?: string }> = {
  '3869685': {
    title: 'Messi v Mbappé',
    detail: '2022 World Cup final · Argentina v France · 18 Dec 2022',
    result: 'Argentina 3–3 France, Argentina win 4–2 on penalties',
  },
  '3754092': {
    title: 'Battle of the Bridge',
    detail: 'Premier League · Chelsea v Tottenham · 2 May 2016',
    result: 'Chelsea 2–2 Tottenham: Leicester are champions',
  },
  '3913122': {
    title: 'Brighton v Bristol City', // the long tail: a league match, not a famous one
    detail: "Women's Super League · Brighton v Bristol City · 21 Jan 2024",
    result: "Brighton 3–2 Bristol City, Terland's winner in stoppage time",
    // Not "no description": Brighton's ground has in-stadium receivers; no broadcast or stream was described
    note: 'No described broadcast',
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
    title: "Jordan's last shot as a Bull", // his last game was 2003, with the Wizards
    detail: '1998 NBA Finals, Game 6 · Jazz v Bulls · 14 Jun 1998',
    result: 'Bulls 87–86 Jazz',
  },
  '9636': {
    title: 'Verstappen, P17 to P1',
    detail: '2024 São Paulo Grand Prix · Interlagos · 3 Nov 2024',
    result: 'Verstappen wins by 19.5\u00a0s from Ocon, Gasly third',
    crest: 'Verstappen', // a race has no sides: the card shows the driver it is remembered for
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

// The dock chip's name, short enough for a phone and never a lone nationality ("British"): the voice's own
// name before a colon or comma ("Connor: British, energetic" is "Connor", "Raju, Cricket Commentator" is "Raju"),
// else a pick's role words ("British Football Announcer" is "Football Announcer"), as the sheet names it (#154).
export function chipName(v: Voice | null): string {
  if (!v) return ''
  if (v.browser) return 'Browser voice'
  const own = /^([^:,(]+)[:,]/.exec(v.label)
  if (own) return own[1].trim()
  const words = v.label.split(/\s+/)
  return words.length > 2 ? words.slice(-2).join(' ') : v.label
}

// The voice sheet's name for an option: a voice with a description shows it whole ("Connor: British,
// energetic"); a pick shows the dock chip's name, so the bar and the sheet agree and fit a phone (#154).
export const sheetName = (v: Voice): string => (/[:,(]/.test(v.label) ? v.label : chipName(v))

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

// The wall by sport; within one, the long tail (a card with a note) before the famous replays
export function wallOrder(matches: Match[]): Match[] {
  const rank = (m: Match) => SPORTS.indexOf(m.sport) * 2 + (CARD_COPY[m.match_id]?.note ? 0 : 1)
  return [...matches].sort((a, b) => rank(a) - rank(b))
}
