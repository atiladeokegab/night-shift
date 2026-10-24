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
