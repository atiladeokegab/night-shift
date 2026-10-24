import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import type { Match, Moment, Sport } from './types.ts'
import { chipName, commentatorName, cricketScore, sheetVoices, voiceName } from './teams.ts'

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
  assert.equal(chipName(voice('Football pick')), 'Football pick')
  assert.equal(chipName({ ...voice('British (browser)'), browser: true }), 'Browser voice')
  assert.equal(chipName(null), '')
})

test('the ON AIR badge names the voice as the dock chip does', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /const voiceLabel = voice\.chip\b/)
  assert.match(live, /<OnAir voice=\{voice\} label=\{voiceLabel\}[ />]/)
})

test('a commentator error shows the calm off-air state with a Retry, never the error text', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /replay\.error \? \([\s\S]*?Commentator is off air for a moment[\s\S]*?onClick=\{onRetry\}>Retry</)
  assert.doesNotMatch(live, /\{replay\.error\}/)
})

test('while off air the badge reads OFF AIR, and a voice change is announced by its chip name', () => {
  const live = readFileSync(new URL('./components/Live.tsx', import.meta.url), 'utf8')
  assert.match(live, /offAir=\{!!replay\.error\}/)
  assert.match(live, /if \(offAir\) \{[\s\S]*?className="onair glass off"[\s\S]*?OFF AIR/)
  const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8')
  assert.match(app, /say\(`\$\{chipName\(v\)\} from the next line\.`\)/)
})
