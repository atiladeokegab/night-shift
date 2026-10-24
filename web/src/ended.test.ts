import assert from 'node:assert/strict'
import { test } from 'node:test'
import { converseDoor } from './converse.ts'
import { ENDED, gone, replayGone } from './ended.ts'

const reply = (status: number, detail: string) => new Response(JSON.stringify({ detail }), { status, headers: { 'Content-Type': 'application/json' } })

test("only the server's 404 \"no replay\" means the replay has ended, and it says which one (#454)", async () => {
  const heard: string[] = []
  const on = (e: Event) => heard.push((e as CustomEvent<string>).detail)
  gone.addEventListener('replay-gone', on)
  assert.equal(await replayGone(reply(404, "no replay 'r1'"), 'r1'), true)
  assert.equal(await replayGone(reply(404, "no replay of football match '7'"), 'r2'), true) // Talk's token
  // a 404 about something else in a live replay is not an ended replay
  assert.equal(await replayGone(reply(404, 'no such player in this match'), 'r3'), false)
  assert.equal(await replayGone(reply(404, "no shot map for 'Kane' in this match"), 'r3'), false)
  assert.equal(await replayGone(reply(429, 'busy'), 'r3'), false)
  assert.equal(await replayGone(new Response('not json', { status: 404 }), 'r3'), false)
  gone.removeEventListener('replay-gone', on)
  assert.deepEqual(heard, ['r1', 'r2'])
  assert.match(ENDED, /This replay has ended/)
})

test("Talk's token on a dropped replay signals it ended and still returns no door (#454)", async () => {
  const heard: string[] = []
  const on = (e: Event) => heard.push((e as CustomEvent<string>).detail)
  gone.addEventListener('replay-gone', on)
  const dropped = (async () => reply(404, "no replay of football match '7'")) as typeof fetch
  assert.equal(await converseDoor('r9', 'football', '7', 3, dropped), null)
  gone.removeEventListener('replay-gone', on)
  assert.deepEqual(heard, ['r9'])
})
