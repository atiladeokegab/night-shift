import assert from 'node:assert/strict'
import { test } from 'node:test'
import { embeds, loadYouTube, mountPlayer, posterUrl, showNoVideoCaption, watchUrl } from './player.ts'

test('an embed-blocked video never plays here: it gets a poster and a link to YouTube at its first moment', () => {
  assert.equal(embeds({ youtube_id: '46nYnjGdQlk', video_start: 7 }), true)
  assert.equal(embeds({ youtube_id: 'yPvoKz6tyJs', video_start: 0, embed: false }), false)
  assert.equal(embeds({}), false)
  assert.equal(posterUrl('yPvoKz6tyJs'), 'https://i.ytimg.com/vi/yPvoKz6tyJs/hqdefault.jpg')
  assert.equal(watchUrl({ youtube_id: 'jD1GwCcJV-0', video_start: 25.6, embed: false }), 'https://www.youtube.com/watch?v=jD1GwCcJV-0&t=25s')
})

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

function mount(startMs = 1000, vars?: Record<string, string | number>) {
  const calls: string[] = []
  const hooks = {
    onClock: (c: unknown) => calls.push(c ? 'clock' : 'clock null'),
    onState: (s: string) => calls.push(s),
    onPlaying: () => calls.push('playing'),
  }
  const cleanup = mountPlayer(api, {} as HTMLElement, 'abcdefghijk', 485, hooks, startMs, vars)
  return { player: FakePlayer.made.at(-1)!, calls, cleanup }
}

test('the video starts at the given second', () => {
  const m = mount()
  assert.equal(m.player.options.playerVars!.start, 485)
  m.cleanup()
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

test('a player that never answers at all gives up after the start timeout', async () => {
  const m = mount(20)
  await sleep(40)
  assert.deepEqual(m.calls, ['clock null', 'unavailable'])
  assert.ok(m.player.destroyed)
})

test('a player that starts playing in time keeps its clock', async () => {
  const m = mount(20)
  m.player.ready()
  m.player.change(PlayerState.PLAYING)
  await sleep(40)
  assert.deepEqual(m.calls, ['ok', 'clock', 'playing'])
  m.cleanup()
})

// A wall tile (A-6.5): it shows its clip only on onPlaying, and settles on its poster on 'unavailable'.
test('a wall tile clip loops without captions and is shown only once it is really playing', () => {
  const m = mount(1000, { loop: 1, playlist: 'abcdefghijk', cc_load_policy: 0 })
  assert.equal(m.player.options.playerVars!.loop, 1)
  assert.equal(m.player.options.playerVars!.cc_load_policy, 0)
  assert.equal(m.player.options.playerVars!.start, 485)
  m.player.ready() // ready is not playing: the black-tile bug
  m.player.change(PlayerState.BUFFERING)
  assert.ok(!m.calls.includes('playing'))
  m.player.change(PlayerState.PLAYING)
  assert.deepEqual(m.calls, ['ok', 'clock', 'playing'])
  m.cleanup()
})

test('a wall tile clip that is ready but never plays gives up, and never shows', async () => {
  const m = mount(20, { loop: 1 })
  m.player.ready()
  await sleep(40)
  assert.deepEqual(m.calls, ['ok', 'clock', 'clock null', 'unavailable'])
  m.player.change(PlayerState.PLAYING) // a destroyed player's late PLAYING
  assert.ok(!m.calls.includes('playing'))
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

test('the no-video caption shows only while no alert banner holds its slot', () => {
  const live = { phase: 'live', stream: 'ok', error: null } as const
  assert.equal(showNoVideoCaption(live, 'unavailable'), true)
  assert.equal(showNoVideoCaption(live, 'ok'), false)
  assert.equal(showNoVideoCaption({ ...live, phase: 'starting' }, 'unavailable'), false)
  assert.equal(showNoVideoCaption({ ...live, stream: 'reconnecting' }, 'unavailable'), false)
  assert.equal(showNoVideoCaption({ ...live, stream: 'disconnected' }, 'unavailable'), false)
  assert.equal(showNoVideoCaption({ ...live, error: 'The commentator stopped.' }, 'unavailable'), false)
})
