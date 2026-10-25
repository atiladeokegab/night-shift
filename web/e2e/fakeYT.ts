import type { Page } from '@playwright/test'

// The IFrame API's slice the page uses, on a clock of its own: it plays from `start`, pauses and seeks.
export const FAKE_YT = `(() => {
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

// #514: Ask and Talk open at a match's first mapped event. This seeks the playing fake player there, once its
// clock is behind `t` (a new match's player, not the last one's).
// data/video/: where Kobe's 81 (from 478 s) and Argentina v France (from 69 s) reach their first mapped event
export const KOBE_FIRST = 490.5
export const ARGENTINA_FIRST = 81.1

export async function toFirstEvent(page: Page, t: number) {
  await page.waitForFunction((t) => {
    const p = (window as unknown as { fakePlayer?: { getPlayerState(): number; getCurrentTime(): number } }).fakePlayer
    return p?.getPlayerState() === 1 && p.getCurrentTime() < t
  }, t)
  await page.evaluate((t) => (window as unknown as { fakePlayer: { seekTo(t: number): void } }).fakePlayer.seekTo(t), t)
}
