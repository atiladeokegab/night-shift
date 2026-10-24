import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Match, Moment, Sport } from './types.ts'
import { commentatorName, cricketScore, sheetVoices, voiceName } from './teams.ts'

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
