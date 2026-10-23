import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadYouTube, mountPlayer } from './player.ts'

// A stand-in for the IFrame API: each player keeps its options, so a test fires its events when it likes.
const PlayerState = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 }
class FakePlayer {
  static made: FakePlayer[] = []
  options: YT.PlayerOptions
  state = -1
  destroyed = false
  constructor(_el: unknown, options: YT.PlayerOptions) {
    this.options = options
    FakePlayer.made.push(this)
  }
  playVideo() {}
  mute() {}
  getCurrentTime() { return 0 }
  getDuration() { return 600 }
  getPlayerState() { return this.state }
  destroy() { this.destroyed = true }
  ready() { this.options.events!.onReady!({ target: this as unknown as YT.Player }) }
  change(state: number) { this.options.events!.onStateChange!({ target: this as unknown as YT.Player, data: state }) }
  error() { this.options.events!.onError!({ target: this as unknown as YT.Player }) }
}
const api = { Player: FakePlayer, PlayerState } as unknown as typeof YT
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function mount(startMs = 1000) {
  const calls: string[] = []
  const hooks = {
    onClock: (c: unknown) => calls.push(c ? 'clock' : 'clock null'),
    onState: (s: string) => calls.push(s),
  }
  const cleanup = mountPlayer(api, {} as HTMLElement, 'abcdefghijk', 485, hooks, startMs)
  return { player: FakePlayer.made.at(-1)!, calls, cleanup }
}

test('the video starts at the given second', () => {
  assert.equal(mount().player.options.playerVars!.start, 485)
})

test("a destroyed player's late onError leaves the new player's clock alone", () => {
  const old = mount()
  old.player.ready()
  old.cleanup() // a sport switch: the next match's player now owns the clock
  const before = [...old.calls]
  old.player.error()
  assert.deepEqual(old.calls, before)
})

test("a destroyed player's late onReady never hands over its clock", () => {
  const old = mount()
  old.cleanup()
  old.player.ready()
  assert.deepEqual(old.calls, ['clock null'])
})

test('a player that errors gives up once: clock cleared, video unavailable, player destroyed', () => {
  const m = mount()
  m.player.ready()
  m.player.error()
  m.player.error()
  m.cleanup()
  assert.deepEqual(m.calls, ['ok', 'clock', 'clock null', 'unavailable'])
  assert.ok(m.player.destroyed)
})

test('a ready player that never starts playing gives up after the start timeout', async () => {
  const m = mount(20)
  m.player.ready()
  m.player.change(PlayerState.BUFFERING)
  await sleep(40)
  assert.deepEqual(m.calls, ['ok', 'clock', 'clock null', 'unavailable'])
})

test('a player that starts playing in time keeps its clock', async () => {
  const m = mount(20)
  m.player.ready()
  m.player.change(PlayerState.PLAYING)
  await sleep(40)
  assert.deepEqual(m.calls, ['ok', 'clock'])
  m.cleanup()
})

test('an IFrame API script that never loads rejects after the timeout, and the next try loads again', async () => {
  const scripts: unknown[] = []
  Object.assign(globalThis, {
    window: {},
    document: { createElement: () => ({}), head: { appendChild: (s: unknown) => scripts.push(s) } },
  })
  await assert.rejects(loadYouTube(20), /did not load in time/)
  await assert.rejects(loadYouTube(20))
  assert.equal(scripts.length, 2)
})
