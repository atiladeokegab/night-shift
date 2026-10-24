import assert from 'node:assert/strict'
import { test } from 'node:test'
import { submitFix } from './fix.ts'

const fix = { line_id: 'old', corrected_text: 'Saved by Arnold!', reason: 'Wrong player' }

function later<T>(value: T, fail = false) {
  let settle!: () => void
  const promise = new Promise<T>((resolve, reject) => {
    settle = () => (fail ? reject(new Error('503')) : resolve(value))
  })
  return { promise, settle }
}

for (const fail of [false, true]) {
  test(`a fix ${fail ? 'failure' : 'answer'} that lands after a sport switch touches nothing`, async () => {
    let session = 1
    const seen: string[] = []
    const post = later(fix, fail)
    const sending = submitFix(() => post.promise, () => session === 1, () => seen.push('done'), () => seen.push('failed'))
    session = 2 // switched to the next match, whose own sheet may be open now
    post.settle()
    await sending
    assert.deepEqual(seen, [])
  })
}

test('a fix answer in the same session closes the sheet and marks the line', async () => {
  const seen: unknown[] = []
  await submitFix(() => Promise.resolve(fix), () => true, (f) => seen.push(f), () => seen.push('failed'))
  assert.deepEqual(seen, [fix])
})

test('a failed fix in the same session keeps the sheet open with its error', async () => {
  const seen: string[] = []
  await submitFix(() => Promise.reject(new Error('503')), () => true, () => seen.push('done'), () => seen.push('failed'))
  assert.deepEqual(seen, ['failed'])
})

test("a fix the number check refused hands the sheet the check's reasons (#232)", async () => {
  const seen: unknown[] = []
  const refused = Object.assign(new Error('422'), { status: 422, wrong: ['58 is not in the moment'] })
  await submitFix(() => Promise.reject(refused), () => true, () => {}, (why) => seen.push(why))
  await submitFix(() => Promise.reject(new Error('503')), () => true, () => {}, (why) => seen.push(why))
  assert.deepEqual(seen, [{ status: 422, wrong: ['58 is not in the moment'] }, { status: 0, wrong: [] }])
})
