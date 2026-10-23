import { useEffect, useRef } from 'react'
import { loadYouTube, mountPlayer, type VideoState } from '../player'
import type { Clock } from '../useReplay'

export type { VideoState }

interface Props {
  youtubeId?: string
  start: number // seconds into the video to start at: just before its first mapped moment
  onClock: (clock: Clock | null) => void
  onState: (state: VideoState) => void
}

// The stage (A-6.1@2): the match's broadcast highlights, embedded and muted, full-bleed under the
// overlays. Mounted when a replay starts, so the video starts with it. It hands the replay the player's
// clock (A-6.4@2): lines wait for the picture, and a paused or buffering player holds them.
export function VideoStage({ youtubeId, start, onClock, onState }: Props) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!youtubeId || !host.current) {
      onState('unavailable')
      return
    }
    onState('loading')
    const target = document.createElement('div')
    host.current.appendChild(target)
    let gone = false
    let unmount: (() => void) | undefined
    loadYouTube().then(
      (api) => {
        if (!gone) unmount = mountPlayer(api, target, youtubeId, start, { onClock, onState })
      },
      // The IFrame API never came: no video here, so the commentary carries on without it.
      () => gone || onState('unavailable'),
    )
    return () => {
      gone = true
      unmount?.()
      target.remove()
    }
  }, [youtubeId, start, onClock, onState])

  return <div className="player" ref={host} />
}
