import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import type { Moment, StreamEvent } from './types.ts'
import { demoMatches, streamDemo } from './demo.ts'

const sample = (sport: string, id: string) => new URL(`../../data/sample/${sport}-${id}.json`, import.meta.url)

// Plays a demo feed to the end at once, collecting its moments.
function demoMoments(id: string): Moment[] {
  const moments: Moment[] = []
  const g = globalThis as unknown as { window?: unknown }
  g.window = { setTimeout: (fn: () => void) => (fn(), 0) }
  try {
    streamDemo(id, (e: StreamEvent) => { if (e.type === 'moment') moments.push(e.moment) })
  } finally {
    delete g.window
  }
  return moments
}

test('?demo replays only matches in data/sample/', () => {
  for (const m of demoMatches) assert.ok(existsSync(sample(m.sport, m.match_id)), `${m.match_id} has no sample`)
})

test("every ?demo moment is a real one from its match's sample: same players, outcome, score and spot", () => {
  for (const m of demoMatches) {
    const real: Moment[] = JSON.parse(readFileSync(sample(m.sport, m.match_id), 'utf-8')).moments
    const moments = demoMoments(m.match_id)
    assert.ok(moments.length > 0, `${m.match_id} replays nothing`)
    for (const d of moments) {
      const r = real.find((x) => x.period === d.period && x.clock === d.clock)
      assert.ok(r, `${m.match_id} ${d.clock} is not in the sample`)
      const { idx: _, ...fields } = d
      for (const [k, v] of Object.entries(fields)) {
        const want = (r as unknown as Record<string, unknown>)[k]
        if (v && typeof v === 'object') for (const [sk, sv] of Object.entries(v)) assert.deepEqual(sv, (want as Record<string, unknown>)[sk], `${m.match_id} ${d.clock} ${k}.${sk}`)
        else assert.equal(v, want, `${m.match_id} ${d.clock} ${k}`)
      }
    }
  }
})
