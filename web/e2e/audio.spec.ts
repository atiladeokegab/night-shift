import { expect, test, type Page } from '@playwright/test'

// The voice in a real browser (#248): a line arrives and its audio plays; a line whose audio fails is still
// captioned and spoken by the browser, and the next line's audio plays; pause stops the voice and releases
// nothing; play picks the queue up again. Offline: a fake YouTube player and a fake voice stand in.

const KOBE = /^Basketball ?Kobe's 81/

// One second of silence: the voice route's stand-in for an ElevenLabs line.
function silence(): Buffer {
  const rate = 8000
  const wav = Buffer.alloc(44 + rate, 128)
  wav.write('RIFF', 0)
  wav.writeUInt32LE(36 + rate, 4)
  wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16)
  wav.writeUInt16LE(1, 20) // PCM
  wav.writeUInt16LE(1, 22) // mono
  wav.writeUInt32LE(rate, 24)
  wav.writeUInt32LE(rate, 28)
  wav.writeUInt16LE(1, 32)
  wav.writeUInt16LE(8, 34)
  wav.write('data', 36)
  wav.writeUInt32LE(rate, 40)
  return wav
}

// The IFrame API's slice the page uses, on a clock of its own: it plays from `start`, pauses and seeks.
const FAKE_YT = `(() => {
  const S = { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 }
  class Player {
    constructor(_target, opts) {
      this.opts = opts; this.t = opts.playerVars?.start ?? 0; this.since = 0; this.state = S.UNSTARTED
      window.fakePlayer = this
      setTimeout(() => opts.events?.onReady?.({ target: this }), 50)
    }
    now() { return this.state === S.PLAYING ? this.t + (performance.now() - this.since) / 1000 : this.t }
    playVideo() {
      if (this.state === S.PLAYING) return
      this.since = performance.now(); this.state = S.PLAYING
      this.opts.events?.onStateChange?.({ data: S.PLAYING, target: this })
    }
    pauseVideo() { this.t = this.now(); this.state = S.PAUSED }
    seekTo(t) { this.t = t; this.since = performance.now() }
    getCurrentTime() { return this.now() }
    getPlayerState() { return this.state }
    getDuration() { return 3600 }
    mute() {}
    destroy() {}
  }
  window.YT = { Player, PlayerState: S }
  window.onYouTubeIframeAPIReady?.()
})()`

type Heard = { heard: string[]; captions: string[]; audios: HTMLAudioElement[]; fakePlayer: { getCurrentTime(): number } }

// Records what the page says: each audio element that starts playing, each line the browser speaks (it
// ends after 300 ms, as a headless browser has no voice of its own), and each caption shown.
async function listen(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as Heard
    w.heard = []
    w.captions = []
    w.audios = []
    const play = HTMLMediaElement.prototype.play
    HTMLMediaElement.prototype.play = function () {
      w.audios.push(this as HTMLAudioElement)
      this.addEventListener('playing', () => w.heard.push(`audio ${this.src}`), { once: true })
      return play.call(this)
    }
    window.speechSynthesis.speak = (u: SpeechSynthesisUtterance) => {
      w.heard.push(`speech ${u.text}`)
      setTimeout(() => u.onend?.(new SpeechSynthesisEvent('end', { utterance: u })), 300)
    }
    window.speechSynthesis.cancel = () => {}
    new MutationObserver(() => {
      const text = document.querySelector('.caption .cap-text')?.textContent
      if (text && w.captions.at(-1) !== text) w.captions.push(text)
    }).observe(document, { subtree: true, childList: true, characterData: true })
  })
}
const videoTime = (page: Page) => page.evaluate(() => (window as unknown as Heard).fakePlayer.getCurrentTime())
const heard = (page: Page) => page.evaluate(() => (window as unknown as Heard).heard)
const captions = (page: Page) => page.evaluate(() => (window as unknown as Heard).captions)
// A failed load leaves an element unpaused with an error: it says nothing.
const onAir = (page: Page) =>
  page.evaluate(() => (window as unknown as Heard).audios.some((a) => !a.paused && !a.ended && !a.error))

test.use({ launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] } })

test('each line is voiced, a failed voice falls back, and pause holds the queue', async ({ page }) => {
  let asked = 0
  await page.route('https://www.youtube.com/iframe_api', (r) => r.fulfill({ contentType: 'text/javascript', body: FAKE_YT }))
  await page.route(/ytimg\.com|youtube(-nocookie)?\.com\/(?!iframe_api)/, (r) => r.abort())
  // The second line's voice fails, as an ElevenLabs outage would; every other line gets its audio.
  await page.route('**/lines/*/audio*', (r) =>
    ++asked === 2 ? r.fulfill({ status: 503, body: 'voice upstream failed' }) : r.fulfill({ contentType: 'audio/wav', body: silence() }))
  await listen(page)
  await page.goto('/')
  await page.getByRole('button', { name: KOBE }).click()

  // A line arrives: its audio element plays.
  await expect.poll(() => heard(page), { timeout: 60_000 }).toContainEqual(expect.stringMatching(/^audio .*\/lines\/.+\/audio/))

  // Its voice fails: the line is still captioned and spoken by the browser, and the next line's audio plays.
  await expect.poll(async () => (await heard(page)).find((h) => h.startsWith('speech ')), { timeout: 60_000 }).toBeTruthy()
  const said = await heard(page)
  const fell = said.findIndex((h) => h.startsWith('speech '))
  expect(await captions(page)).toContain(said[fell].slice('speech '.length))
  await expect.poll(async () => (await heard(page)).slice(fell + 1).some((h) => h.startsWith('audio ')), { timeout: 60_000 }).toBe(true)

  // Paused mid-line: the voice stops at once, the picture holds (no line falls due), and nothing is said.
  await expect.poll(() => onAir(page), { timeout: 60_000 }).toBe(true)
  await page.getByRole('button', { name: 'Pause' }).click()
  expect(await onAir(page)).toBe(false)
  const before = (await heard(page)).length
  const at = await videoTime(page)
  await page.waitForTimeout(5000)
  expect(await videoTime(page)).toBe(at)
  expect(await heard(page)).toHaveLength(before)

  // Play: the picture moves on, and with it the queue.
  await page.getByRole('button', { name: 'Play' }).click()
  await expect.poll(() => videoTime(page)).toBeGreaterThan(at)
  await expect.poll(async () => (await heard(page)).slice(before).some((h) => h.startsWith('audio ')), { timeout: 60_000 }).toBe(true)
})
