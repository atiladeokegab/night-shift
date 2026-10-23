import { useEffect, useRef, useState } from 'react'
import { CARD_COPY } from '../teams'
import { SPORT_NAMES, type Match } from '../types'
import { Nav, type Screen } from './Nav'
import { loadYouTube } from '../player'

interface Props {
  matches: Match[] | null // null while loading
  error: boolean
  onRetry: () => void
  onOpen: (match: Match) => void
  onGo: (screen: Screen) => void
}

// The match wall (A-6.5): the home page, one tile per match, each playing its highlights muted with no
// commentary. Tapping a tile opens it on the full live stage, where the commentator calls it.
export function Wall({ matches, error, onRetry, onOpen, onGo }: Props) {
  let body
  if (error) {
    body = (
      <div className="notice glass err" role="alert">
        Couldn't load matches. Is the server running?
        <button className="btn" onClick={onRetry}>Try again</button>
      </div>
    )
  } else if (matches === null) {
    body = (
      <>
        <p className="status-line" role="status">Loading matches…</p>
        <div className="wall" aria-hidden><div className="tile ghost" /><div className="tile ghost" /><div className="tile ghost" /></div>
      </>
    )
  } else if (matches.length === 0) {
    body = <div className="notice glass">No matches yet. Load the demo data, then refresh.</div>
  } else {
    body = <div className="wall">{matches.map((m) => <Tile key={m.match_id} match={m} onOpen={onOpen} />)}</div>
  }
  return (
    <div className="page">
      <Nav current="wall" onGo={onGo} />
      <main className="wrap">
        <p className="eyebrow">A live AI commentator for matches nobody calls.</p>
        <h1>Tap a match to hear it called</h1>
        {body}
        <p className="foot">
          Match data: StatsBomb open data, Cricsheet, NBA play-by-play and OpenF1. Highlights: broadcast highlights on
          YouTube, embedded, muted. Commentary is AI-generated.
        </p>
      </main>
    </div>
  )
}

function Tile({ match, onOpen }: { match: Match; onOpen: (m: Match) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [broken, setBroken] = useState(!match.youtube_id)
  const title = CARD_COPY[match.match_id]?.title ?? match.title?.split(',')[0] ?? match.match_id
  const detail = CARD_COPY[match.match_id]?.detail ?? match.title?.split(',').slice(1).join(',').trim()

  // Muted, looping and without controls: the tile is a moving picture, never a second commentary.
  useEffect(() => {
    if (!match.youtube_id || !host.current) return
    const target = document.createElement('div')
    host.current.appendChild(target)
    let player: YT.Player | null = null
    let gone = false
    // GET /matches' video_start (#73) is already just before the first mapped moment.
    const start = Math.max(0, Math.floor(match.video_start ?? 0))
    loadYouTube().then((YT) => {
      if (gone) return
      player = new YT.Player(target, {
        videoId: match.youtube_id!,
        host: 'https://www.youtube-nocookie.com',
        playerVars: { autoplay: 1, mute: 1, controls: 0, playsinline: 1, rel: 0, modestbranding: 1, disablekb: 1, loop: 1, playlist: match.youtube_id!, start },
        events: {
          onReady: (e) => {
            if (gone) return
            e.target.mute()
            e.target.playVideo()
            setPlaying(true)
          },
          onError: () => !gone && setBroken(true),
        },
      })
    }, () => !gone && setBroken(true)) // the IFrame API never loaded (player.ts gives up after 10 s)
    return () => {
      gone = true
      player?.destroy()
      target.remove()
    }
  }, [match.youtube_id, match.video_start])

  return (
    <button className="tile" onClick={() => onOpen(match)} aria-label={`Watch ${title} with commentary`}>
      {match.youtube_id && (
        <img className="poster" alt="" loading="lazy" onError={(e) => { e.currentTarget.hidden = true }} src={`https://i.ytimg.com/vi/${encodeURIComponent(match.youtube_id)}/hqdefault.jpg`} />
      )}
      <div className={`clip${playing && !broken ? ' on' : ''}`} ref={host} aria-hidden />
      <span className="tile-shade" />
      <span className="tile-body">
        <span className="label">{SPORT_NAMES[match.sport]}</span>
        <span className="tile-title">{title}</span>
        {detail && <span className="tile-detail">{detail}</span>}
        <span className="tile-cta">{broken ? 'Highlights unavailable here · Tap for commentary' : 'Tap to hear it called →'}</span>
      </span>
    </button>
  )
}
