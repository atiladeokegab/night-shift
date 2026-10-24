import assert from 'node:assert/strict'
import { test } from 'node:test'
import { canWatch, SHARE, watch, WIDTH } from './look.ts'

// Let them watch (#291): the frame pipeline with a fake getDisplayMedia, video and canvas (node has none).
class Track extends EventTarget {
  stopped = false
  stop() {
    this.stopped = true
  }
}

function fakes(size = { w: 1280, h: 720 }) {
  const track = new Track()
  const stream = { getTracks: () => [track], getVideoTracks: () => [track] }
  const asked: unknown[] = []
  const media = { getDisplayMedia: async (o: unknown) => (asked.push(o), stream) } as unknown as MediaDevices
  const video = { muted: false, srcObject: null as unknown, videoWidth: size.w, videoHeight: size.h, play: async () => {} }
  const drawn: number[][] = []
  const canvas = {
    width: 0, height: 0,
    getContext: () => ({ drawImage: (_v: unknown, ...xywh: number[]) => drawn.push(xywh) }),
    toDataURL: (type: string, q: number) => `data:${type};base64,/9j/FRAME${drawn.length}q${q}`,
  }
  const make = (tag: string) => (tag === 'video' ? video : canvas) as unknown as HTMLElement
  return { track, stream, asked, media, video, canvas, drawn, make }
}

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms))

test('no getDisplayMedia, no watching', () => {
  assert.equal(canWatch(undefined), false)
  assert.equal(canWatch({}), false)
  assert.equal(canWatch(fakes().media), true)
})

test('sharing asks Chrome for this tab, then sends a 512 px JPEG frame at once and on every tick', async () => {
  const f = fakes()
  const sent: string[] = []
  const stop = await watch(f.media, async (image) => (sent.push(image), true), () => {}, f.make, 20)
  assert.deepEqual(f.asked, [{ video: true, preferCurrentTab: true, selfBrowserSurface: 'include' }])
  assert.deepEqual(f.asked[0], SHARE)
  assert.equal(f.video.muted, true)
  assert.equal(f.video.srcObject, f.stream)
  assert.deepEqual(sent, ['/9j/FRAME1q0.7']) // the base64 alone, no data: prefix
  assert.deepEqual([f.canvas.width, f.canvas.height], [WIDTH, 288])
  assert.deepEqual(f.drawn[0], [0, 0, 512, 288])
  await tick(70)
  assert.ok(sent.length >= 3, `a frame per tick: ${sent.length}`)
  stop()
})

test('Chrome\'s own Stop sharing ends it at once: tracks stopped, no more frames, onEnd once', async () => {
  const f = fakes()
  const sent: string[] = []
  let ended = 0
  const stop = await watch(f.media, async (image) => (sent.push(image), true), () => ended++, f.make, 20)
  f.track.dispatchEvent(new Event('ended'))
  const n = sent.length
  await tick(70)
  assert.equal(sent.length, n)
  assert.equal(f.track.stopped, true)
  assert.equal(f.video.srcObject, null)
  stop() // the chip's Stop after the fact: nothing more
  assert.equal(ended, 1)
})

test('the server taking no more frames stops the sharing; a slow send skips frames, never piles them up', async () => {
  const f = fakes()
  let ended = 0
  const said: boolean[] = [true, false]
  await watch(f.media, async () => said.shift() ?? true, () => ended++, f.make, 10)
  await tick(50)
  assert.equal(ended, 1)
  assert.equal(f.track.stopped, true)

  const g = fakes()
  let inFlight = 0
  let most = 0
  const stop = await watch(g.media, async () => {
    most = Math.max(most, ++inFlight)
    await tick(45)
    inFlight--
    return true
  }, () => {}, g.make, 10)
  await tick(100)
  stop()
  assert.equal(most, 1)
})

test('no frame before the picture has a size; the viewer saying no throws, and nothing is sent', async () => {
  const f = fakes({ w: 0, h: 0 })
  const sent: string[] = []
  const stop = await watch(f.media, async (i) => (sent.push(i), true), () => {}, f.make, 10)
  await tick(30)
  stop()
  assert.deepEqual(sent, [])
  const no = { getDisplayMedia: async () => { throw new DOMException('denied', 'NotAllowedError') } } as unknown as MediaDevices
  await assert.rejects(watch(no, async () => true, () => {}, f.make), /denied/)
})
