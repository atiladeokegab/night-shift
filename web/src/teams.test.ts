import assert from 'node:assert/strict'
import { test } from 'node:test'
import { commentatorName, voiceName } from './teams.ts'

const voice = (label: string) => ({ id: 'v', label, lang: 'en-GB', default_for: null })

test("a pick shows the voice's own name; the built-in voices keep their short name", () => {
  assert.equal(voiceName(voice('British Football Announcer')), 'British Football Announcer')
  assert.equal(commentatorName(voiceName(voice('British Football Announcer'))), 'British Football Announcer')
  assert.equal(commentatorName(voiceName(voice('Connor: British, energetic'))), 'British commentator')
  assert.equal(voiceName(voice('Viraj: Indian English, energetic')), 'Indian')
  assert.equal(voiceName(voice('British (browser)')), 'British')
})
