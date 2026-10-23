// The slice of the YouTube IFrame Player API the stage uses (https://developers.google.com/youtube/iframe_api_reference).
declare namespace YT {
  enum PlayerState {
    UNSTARTED = -1,
    ENDED = 0,
    PLAYING = 1,
    PAUSED = 2,
    BUFFERING = 3,
    CUED = 5,
  }

  interface PlayerEvent {
    target: Player
  }

  interface PlayerOptions {
    videoId: string
    host?: string
    playerVars?: Record<string, string | number>
    events?: { onReady?: (e: PlayerEvent) => void; onError?: (e: PlayerEvent) => void }
  }

  class Player {
    constructor(element: HTMLElement | string, options: PlayerOptions)
    playVideo(): void
    mute(): void
    getCurrentTime(): number
    getDuration(): number
    getPlayerState(): PlayerState
    destroy(): void
  }
}

interface Window {
  YT?: typeof YT
  onYouTubeIframeAPIReady?: () => void
}
