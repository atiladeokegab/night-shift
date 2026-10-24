import assert from 'node:assert/strict'
import { test } from 'node:test'
import { converseDoor, TalkPause } from './converse.ts'

test('the talk pauses the match and resumes it once, when it ended', () => {
  const calls: string[] = []
  const talk = new TalkPause()
  talk.begin(false, () => calls.push('pause'))
  talk.end(() => calls.push('resume'))
  talk.end(() => calls.push('resume'))
  assert.deepEqual(calls, ['pause', 'resume'])
})

test('a match the fan had paused stays paused when the talk ends', () => {
  const calls: string[] = []
  const talk = new TalkPause()
  talk.begin(true, () => calls.push('pause'))
  talk.end(() => calls.push('resume'))
  assert.deepEqual(calls, [])
})

test('the door is the token route for the replay at the moment on screen', async () => {
  let asked = ''
  const get = (async (url: string) => {
    asked = url
    return new Response(JSON.stringify({ signed_url: 'wss://x', ctx: 'abc' }))
  }) as unknown as typeof fetch
  assert.deepEqual(await converseDoor('r1', 'football', '7', 3, get), { signed_url: 'wss://x', ctx: 'abc' })
  assert.equal(asked, '/converse/football/7/token?replay_id=r1&moment_idx=3')
})

test('no door when the server says no or the network fails', async () => {
  const no = (async () => new Response('', { status: 503 })) as unknown as typeof fetch
  const down = (async () => { throw new Error('offline') }) as unknown as typeof fetch
  assert.equal(await converseDoor('r1', 'football', '7', 3, no), null)
  assert.equal(await converseDoor('r1', 'football', '7', 3, down), null)
})
