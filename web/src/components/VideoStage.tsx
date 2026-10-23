import { useEffect, useRef } from 'react'
import type { Clock } from '../useReplay'

export type VideoState = 'loading' | 'ok' | 'unavailable'

interface Props {
  youtubeId?: string
  onClock: (clock: Clock | null) => void
  onState: (state: VideoState) => void
}

// The stage (A-6.1@2): the match's broadcast highlights, embedded and muted, full-bleed under the
// overlays. Mounted when a replay starts, so the video starts with it. It hands the replay the player's
// clock (A-6.4@2): lines wait for the picture, and a paused or buffering player holds them.
export function VideoStage({ youtubeId, onClock, onState }: Props) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!youtubeId || !host.current) {
      onState('unavailable')
      return
    }
    onState('loading')
    const target = document.createElement('div')
    host.current.appendChild(target)
    let player: YT.Player | null = null
    let gone = false
    loadYouTube().then((YT) => {
      if (gone) return
      player = new YT.Player(target, {
        videoId: youtubeId,
        host: 'https://www.youtube-nocookie.com',
        playerVars: { autoplay: 1, mute: 1, playsinline: 1, rel: 0, modestbranding: 1, controls: 0 },
        events: {
          onReady: (e) => {
            // A player whose stage is already gone (a sport switch) must never hand over its clock.
            if (gone) return
            const p = e.target
            p.mute()
            p.playVideo()
            onState('ok')
            onClock(() => {
              const state = p.getPlayerState()
              // Only a moving picture releases lines; ENDED lets the last moments through.
              const playing = state === YT.PlayerState.PLAYING || state === YT.PlayerState.ENDED
              return { t: p.getCurrentTime(), playing, duration: p.getDuration() }
            })
          },
          // The embed won't play here (removed, region-blocked, embedding off): commentary carries on.
          onError: () => {
            onClock(null)
            onState('unavailable')
          },
        },
      })
    })
    return () => {
      gone = true
      onClock(null)
      player?.destroy()
      target.remove()
    }
  }, [youtubeId, onClock, onState])

  return <div className="player" ref={host} />
}

// The IFrame API script defines window.YT and calls onYouTubeIframeAPIReady once; load it once.
let api: Promise<typeof YT> | null = null

function loadYouTube(): Promise<typeof YT> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  api ??= new Promise((resolve) => {
    const before = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      before?.()
      resolve(window.YT!)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    document.head.appendChild(script)
  })
  return api
}
