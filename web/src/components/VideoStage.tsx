import { useEffect, useRef } from 'react'
import type { Clock } from '../useReplay'

interface Props {
  youtubeId?: string
  label: string
  onClock: (clock: Clock | null) => void
}

// The stage (PRD v2+, A-6.1@2): the match's official highlights, embedded and muted, playing behind the
// commentary. Mounted when a replay starts, so the video starts with it. It hands the replay the
// player's clock (A-6.4@2): lines wait for the picture, and a paused or buffering player holds them.
export function VideoStage({ youtubeId, label, onClock }: Props) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!youtubeId || !host.current) return
    const target = document.createElement('div')
    host.current.appendChild(target)
    let player: YT.Player | null = null
    let gone = false
    loadYouTube().then((YT) => {
      if (gone) return
      player = new YT.Player(target, {
        videoId: youtubeId,
        host: 'https://www.youtube-nocookie.com',
        playerVars: { autoplay: 1, mute: 1, playsinline: 1, rel: 0, modestbranding: 1 },
        events: {
          onReady: (e) => {
            e.target.mute()
            e.target.playVideo()
            const p = e.target
            onClock(() => {
              const state = p.getPlayerState()
              // Only a moving picture releases lines; ENDED lets the last moments through.
              return { t: p.getCurrentTime(), playing: state === YT.PlayerState.PLAYING || state === YT.PlayerState.ENDED }
            })
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
  }, [youtubeId, onClock])

  if (!youtubeId) {
    return <div className="video empty">No highlights video for this match yet.</div>
  }
  return <div className="video" ref={host} title={`${label}: official highlights`} />
}

// The IFrame API script defines window.YT and calls onYouTubeIframeAPIReady once; load it once.
let api: Promise<typeof YT> | null = null

function loadYouTube(): Promise<typeof YT> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  api ??= new Promise((resolve) => {
    const before = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      before?.()
      resolve(window.YT)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    document.head.appendChild(script)
  })
  return api
}
