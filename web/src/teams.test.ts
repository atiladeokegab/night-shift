import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import type { Match, Moment, Sport } from './types.ts'
import { CARD_COPY, chipName, coverage, hasTeams, commentatorName, cricketScore, sheetName, sheetVoices, voiceName, wallOrder } from './teams.ts'

const voice = (label: string) => ({ id: 'v', label, lang: 'en-GB', default_for: null })

test("a pick shows the voice's own name; the built-in voices keep their short name", () => {
  assert.equal(voiceName(voice('British Football Announcer')), 'British Football Announcer')
  assert.equal(commentatorName(voiceName(voice('British Football Announcer'))), 'British Football Announcer')
  assert.equal(commentatorName(voiceName(voice('Connor: British, energetic'))), 'British commentator')
  assert.equal(voiceName(voice('Viraj: Indian English, energetic')), 'Indian')
  assert.equal(voiceName(voice('British (browser)')), 'British')
})

test('the cricket score bar shows the batting side, never a first innings that reads as one-all', () => {
  const match = { match_id: '1298150', sport: 'cricket', title: 'Pakistan v India, T20', sample: true } as Match
  const at = (team: string, period: number, runs: number, wickets: number, target?: number) =>
    ({ team, period, score: { runs, wickets, target } }) as Moment
  const brief = (c: ReturnType<typeof cricketScore>) =>
    [c.batting.code, c.score, c.fielding?.team.code, c.fielding?.total].filter(Boolean).join(' ')

  assert.equal(brief(cricketScore(match, null, [])), 'PAK 0/0')
  const pak = at('Pakistan', 1, 1, 1)
  assert.equal(brief(cricketScore(match, pak, [pak])), 'PAK 1/1') // not "PAK 1/1 IND"
  const pakEnd = at('Pakistan', 1, 159, 8)
  const ind = at('India', 2, 138, 4, 160)
  assert.equal(brief(cricketScore(match, ind, [pak, pakEnd, ind])), 'IND 138/4 PAK 159/8')
  assert.equal(brief(cricketScore(match, ind, [ind])), 'IND 138/4 PAK 159') // first innings unseen: target less one
})

test('the voice sheet lists a voice once per sport, as that sport\'s own entry', () => {
  const v = (id: string, default_for?: Sport, same_as?: string) => ({ id, label: id, lang: 'en-GB', default_for, same_as })
  const live = [v('viraj'), v('connor'), v('announcer', 'f1'), v('sam', 'basketball'), v('football-pick', 'football', 'announcer'), v('cricket-pick', 'cricket')]
  const ids = (sport: Sport, chosen?: string) => sheetVoices(live, sport, chosen).map((x) => x.id)
  assert.deepEqual(ids('football'), ['viraj', 'connor', 'football-pick', 'sam', 'cricket-pick'])
  assert.deepEqual(ids('f1'), ['viraj', 'connor', 'announcer', 'sam', 'cricket-pick'])
  assert.deepEqual(ids('basketball'), ['viraj', 'connor', 'announcer', 'sam', 'cricket-pick'])
  assert.deepEqual(ids('football', 'announcer'), ['viraj', 'connor', 'announcer', 'sam', 'cricket-pick']) // the chosen entry stays checked
})

test('the dock chip shows a voice by its own name or its role, never a lone nationality', () => {
  assert.equal(chipName(voice('Raju, Cricket Commentator')), 'Raju')
  assert.equal(chipName(voice('Sam, Engaging Game Narrator')), 'Sam')
  assert.equal(chipName(voice('Connor: British, energetic')), 'Connor')
  assert.equal(chipName(voice('Viraj: Indian English, energetic')), 'Viraj')
  assert.equal(chipName(voice('George: British, warm')), 'George')
  assert.equal(chipName(voice('British Football Announcer')), 'Football Announcer')
  assert.equal(sheetName(voice('British Football Announcer')), 'Football Announcer') // the bar and the sheet agree
  assert.equal(sheetName(voice('Connor: British, energetic')), 'Connor: British, energetic')
  assert.equal(chipName(voice('Football pick')), 'Football pick')
  assert.equal(chipName({ ...voice('British (browser)'), browser: true }), 'Browser voice')
  assert.equal(chipName(null), '')
})

test('the ON AIR badge names the voice as the dock chip does', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /const voiceLabel = voice\.chip\b/)
  assert.match(live, /const onAirLabel = [^\n]*`Lead · \$\{voiceLabel\}`/) // #153: the lead's label is the chip name
  assert.match(live, /<OnAir voice=\{voice\} label=\{onAirLabel\}[ />]/)
})

test('a commentator error shows the calm off-air state with a Retry, never the error text', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /replay\.error \? \([\s\S]*?Commentator is off air for a moment[\s\S]*?onClick=\{onRetry\}>Retry</)
  assert.doesNotMatch(live, /\{replay\.error\}/)
})

test('while off air the badge reads OFF AIR, and a voice change is announced by its chip name', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /offAir=\{!!replay\.error\}/)
  assert.match(live, /if \(offAir\) \{[\s\S]*?cls \+= ' off'[\s\S]*?OFF AIR/)
  const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8')
  assert.match(app, /say\(`\$\{chipName\(v\)\} from the next line\.`\)/)
})

test('the whole matches lead, then the WSL match with its quiet note; the famous ones keep their order', () => {
  const m = (sport: Sport, match_id: string, youtube_id?: string) => ({ sport, match_id, youtube_id }) as Match
  const ids = wallOrder([m('cricket', '1298150', 'v'), m('football', '3869685', 'v'), m('football', '3913122', 'v'),
    m('football', '3754092', 'v'), m('cricket', '1515217'), m('football', '7457')])
  assert.deepEqual(ids.map((x) => x.match_id), ['7457', '1515217', '3913122', '3869685', '3754092', '1298150'])
  assert.equal(CARD_COPY['3913122'].note, 'No described broadcast that we could find')
  assert.equal(coverage(m('football', '7457')), 'Whole match, every key moment')
  assert.equal(coverage(m('football', '3869685', 'v')), 'Highlights, synced to video')
})

test("the home page says #206's name, hook and pitch, and never the claims we can't make", () => {
  const wall = readFileSync(new URL('./components/Wall.tsx', import.meta.url), 'utf8').replace(/\s+/g, ' ')
  for (const said of [
    'Touchline: the describer that checks itself',
    'Every match deserves to be described.', // #246
    'Most matches have no audio description. A blind or low-vision fan following one gets no description.',
    "Touchline describes the matches a platform streams with nobody describing them. It checks the score, the leader and the key numbers before it speaks, fixes what it can itself, sends the rest to a producer, and each fix that passes the number check is recorded in Mubit as training data for that platform's own describer.",
    'replays, as if live',
    'A full replay, mostly highlights, costs', // #257 review: never price a highlights replay as a whole match
  ]) assert.ok(wall.includes(said), said)
  assert.doesNotMatch(wall, /checks every fact|a million matches/i)
})

test('the Teams tab is for sports with sides: absent for F1, present for the rest', () => {
  assert.equal(hasTeams('f1'), false)
  for (const sport of ['football', 'basketball', 'cricket'] as Sport[]) assert.equal(hasTeams(sport), true, sport)
})

test('Live offers the Teams tab and its T shortcut only through hasTeams', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /teamsOn && <button role="tab" id="tab-teams"/)
  assert.match(live, /!teamsOn \|\| e\.key\.toLowerCase\(\) !== 't'/)
})
