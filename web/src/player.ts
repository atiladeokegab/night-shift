import type { Match } from './types'
import type { Clock, ReplayState } from './useReplay'

// The YouTube player behind the stage, kept out of React so a test can hold its callbacks back.

export type VideoState = 'loading' | 'ok' | 'unavailable'

// The "highlights can't play here" caption shares its phone slot with the alert banners, so it waits
// while one is up.
export function showNoVideoCaption(replay: Pick<ReplayState, 'phase' | 'stream' | 'error'>, video: VideoState): boolean {
  return replay.phase === 'live' && video === 'unavailable' && replay.stream === 'ok' && !replay.error
}

type VideoMatch = Pick<Match, 'youtube_id' | 'video_start' | 'embed'>

// A match plays its highlights here only when it has a video and the video's owner allows embedding.
export const embeds = (m: VideoMatch): boolean => !!m.youtube_id && m.embed !== false
export const posterUrl = (youtubeId: string) => `https://i.ytimg.com/vi/${encodeURIComponent(youtubeId)}/hqdefault.jpg`
// A blocked video on YouTube itself, from just before its first mapped moment.
export const watchUrl = (m: VideoMatch) =>
  `https://www.youtube.com/watch?v=${encodeURIComponent(m.youtube_id ?? '')}&t=${Math.floor(m.video_start ?? 0)}s`

export const LOAD_MS = 10_000 // the IFrame API script has this long to load
export const START_MS = 15_000 // a new player has this long to be ready and start playing

interface Hooks {
  onClock: (clock: Clock | null) => void
  onState: (state: VideoState) => void
  onPlaying?: () => void // the picture is actually moving (a wall tile shows its clip only then)
}

// Creates the player in `target` at `start` seconds and returns its cleanup. Every callback checks
// `live` first, so a destroyed player's late onReady, onError or start timer never touches the clock
// of the player that replaced it. A player that errors, or isn't playing `startMs` after it was
// created (never ready, or stuck), gives up for good:
// the stage says so and the replay's own clock takes over (useReplay's unGate). `vars` adds player vars
// (a wall tile loops and hides captions).
export function mountPlayer(api: typeof YT, target: HTMLElement, youtubeId: string, start: number, hooks: Hooks, startMs = START_MS, vars: Record<string, string | number> = {}): () => void {
  let live = true
  let started = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const end = () => {
    live = false
    clearTimeout(timer)
    hooks.onClock(null)
    player.destroy()
  }
  const fail = () => {
    if (!live) return
    end()
    hooks.onState('unavailable')
  }
  const player = new api.Player(target, {
    videoId: youtubeId,
    host: 'https://www.youtube-nocookie.com',
    playerVars: { autoplay: 1, mute: 1, playsinline: 1, rel: 0, modestbranding: 1, controls: 0, start, ...vars },
    events: {
      onReady: (e) => {
        if (!live) return
        const p = e.target
        p.mute()
        p.playVideo()
        hooks.onState('ok')
        hooks.onClock(() => {
          const state = p.getPlayerState()
          // Only a moving picture releases lines; ENDED lets the last moments through.
          const playing = state === api.PlayerState.PLAYING || state === api.PlayerState.ENDED
          return { t: p.getCurrentTime(), playing, duration: p.getDuration() }
        })
      },
      onStateChange: (e) => {
        if (!live || e.data !== api.PlayerState.PLAYING) return
        started = true
        hooks.onPlaying?.()
      },
      // The embed won't play here (removed, region-blocked, embedding off).
      onError: fail,
    },
  })
  // Armed now, not on ready: an iframe that never answers at all still gives up.
  timer = setTimeout(() => started || fail(), startMs)
  return () => {
    if (live) end()
  }
}

// The IFrame API script defines window.YT and calls onYouTubeIframeAPIReady once; load it once. A script
// that fails or hasn't loaded in `loadMs` rejects, and the next stage tries again.
let loading: Promise<typeof YT> | null = null

export function loadYouTube(loadMs = LOAD_MS): Promise<typeof YT> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  loading ??= new Promise<typeof YT>((resolve, reject) => {
    const before = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      before?.()
      resolve(window.YT!)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.onerror = () => reject(new Error('the YouTube IFrame API failed to load'))
    document.head.appendChild(script)
    setTimeout(() => reject(new Error('the YouTube IFrame API did not load in time')), loadMs)
  }).catch((e: unknown) => {
    loading = null
    throw e
  })
  return loading
}
