import { useEffect, useRef, useState } from 'react'
import { cardArt } from '../art'
import { CARD_COPY, coverage, matchTeams } from '../teams'
import { SPORT_NAMES, type Match } from '../types'
import { Nav, type Screen } from './Nav'
import { embeds, loadYouTube, mountPlayer, posterUrl, watchUrl } from '../player'
import '@fontsource/barlow-condensed/700.css'
import '../hero.css'

const TILE_START_MS = 8_000 // a tile clip has this long to start playing before the tile settles on its poster

interface Props {
  matches: Match[] | null // null while loading
  error: boolean
  onRetry: () => void
  onOpen: (match: Match) => void
  onJump: (match: Match) => void // starts at the match's peak_idx (#163)
  onGo: (screen: Screen) => void
}

// The match wall (A-6.5): the home page, one tile per match, each playing its highlights muted with no
// commentary. Tapping a tile opens it on the full live stage, where the commentator calls it.
export function Wall({ matches, error, onRetry, onOpen, onJump, onGo }: Props) {
  // #314: one first action for a cold visitor, a match whose highlights play under the commentary
  const first = matches?.find((m) => embeds(m)) ?? matches?.[0]
  let body
  if (error) {
    body = (
      <div className="notice glass err" role="alert">
        Couldn't load matches. Check the connection and try again.
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
    body = <div className="notice glass">No matches yet.</div>
  } else {
    body = <div className="wall">{matches.map((m) => <Tile key={m.match_id} match={m} onOpen={onOpen} onJump={onJump} />)}</div>
  }
  return (
    <div className="page">
      <Nav current="wall" onGo={onGo} />
      <main className="wrap">
        {/* The featured match, full bleed: its still behind a vignette, the pitch, and the two ways in */}
        <section className="hero">
          {first?.youtube_id && <img className="hero-still" alt="" onError={(e) => { e.currentTarget.hidden = true }} src={posterUrl(first.youtube_id, 'maxresdefault')} />}
          <div className="hero-copy">
            <h1 className="hero-title">Every match deserves to be described.</h1>
            {first && (
              <p className="hero-meta">
                <span>{[SPORT_NAMES[first.sport], cardText(first).detail].filter(Boolean).join(' · ')}</span>
                {cardText(first).note && <span className="hero-badge">{cardText(first).note}</span>}
              </p>
            )}
            {/* #246: the pitch the film makes, audio description for blind and low-vision fans */}
            <p className="hero-line">
              For matches with no audio description, Touchline calls them aloud, checking the score and key numbers before it speaks.
            </p>
            {/* the loading placeholder keeps the height the real button takes, so the page below doesn't jump */}
            {matches === null && !error && (
              <p className="hero-go" aria-hidden style={{ visibility: 'hidden' }}><button className="btn primary" tabIndex={-1}>▶ Hear a match called</button></p>
            )}
            {first && (
              <p className="hero-go">
                <button className="btn primary" onClick={() => onOpen(first)}>▶ Hear a match called</button>
                {first.peak_idx !== undefined && <button className="btn hero-ghost" onClick={() => onJump(first)}>Jump to the big moment</button>}
                <span>Sound on.</span>
              </p>
            )}
          </div>
        </section>
        <div className="rail">{body}</div>
        {/* --muted: .foot's --faint is 3.77:1 at 13 px, under WCAG AA (#154); App.css is #153's until it merges */}
        <p className="foot" style={{ color: 'var(--muted)' }}>
          Match data: StatsBomb open data, Cricsheet, NBA play-by-play and OpenF1. Highlights: broadcast highlights on
          YouTube, embedded and muted where their owners allow it, linked where they don't. Commentary is AI-generated.
        </p>
      </main>
    </div>
  )
}

// "18 Dec 2022" or "Tap for commentary" never breaks across lines on a phone; the line breaks at a " · ".
// A card's title, its "competition · date" line and its long-tail note, from CARD_COPY or the data's title.
function cardText(match: Match) {
  const copy = CARD_COPY[match.match_id]
  return {
    title: copy?.title ?? match.title?.split(',')[0] ?? match.match_id,
    detail: copy?.detail ?? match.title?.split(',').slice(1).join(',').trim(),
    note: copy?.note,
  }
}

const phrases = (text: string) =>
  text.split(' · ').map((part, i) => <span key={i}>{i > 0 && ' · '}<span className="nw">{part}</span></span>)

function Tile({ match, onOpen, onJump }: { match: Match; onOpen: (m: Match) => void; onJump: (m: Match) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const plays = embeds(match)
  const blocked = !!match.youtube_id && !plays // the owner blocks embedding: the poster stays, with a YouTube link
  const [broken, setBroken] = useState(!plays)
  const { title, detail, note } = cardText(match)

  // Muted, looping, without controls or captions: the tile is a moving picture, never a second commentary.
  // The clip shows only once it is really playing; a clip that errors or isn't playing in TILE_START_MS
  // gives up (player.ts's deadline, #73) and the tile keeps its thumbnail poster and its call to tap: on slow
  // wifi the clip is late, not missing (#154). Only a video whose owner blocks embedding says "Commentary only".
  useEffect(() => {
    if (!plays || !host.current) return
    const target = document.createElement('div')
    host.current.appendChild(target)
    let unmount: (() => void) | null = null
    let gone = false
    // GET /matches' video_start (#73) is already just before the first mapped moment.
    const start = Math.max(0, Math.floor(match.video_start ?? 0))
    loadYouTube().then((YT) => {
      if (gone) return
      unmount = mountPlayer(YT, target, match.youtube_id!, start, {
        onClock: () => {},
        onState: (s) => s === 'unavailable' && setBroken(true),
        onPlaying: () => setPlaying(true),
      }, TILE_START_MS, { disablekb: 1, loop: 1, playlist: match.youtube_id!, cc_load_policy: 0, iv_load_policy: 3 })
    }, () => !gone && setBroken(true)) // the IFrame API never loaded (player.ts gives up after 10 s)
    return () => {
      gone = true
      unmount?.()
      target.remove()
    }
  }, [plays, match.youtube_id, match.video_start])

  return (
    // The three long-tail matches (#246) fill the first row, so the famous six sit in an even grid below them
    <div className="tile-wrap">
    <button className="tile" onClick={() => onOpen(match)}>
      {match.youtube_id ? (
        <img className="poster" alt="" loading="lazy" onError={(e) => { e.currentTarget.hidden = true }} src={posterUrl(match.youtube_id, note ? 'maxresdefault' : 'hqdefault')} />
      ) : (
        // a whole match has no video (#246): the picker card's stadium stands in
        <div className="art" dangerouslySetInnerHTML={{ __html: cardArt(match.sport, ...matchTeams(match)) }} />
      )}
      <div className={`clip${playing && !broken ? ' on' : ''}`} ref={host} aria-hidden />
      <span className="tile-shade" />
      <span className="tile-body">
        <span className="label">{SPORT_NAMES[match.sport]}{note && ` · ${note}`}</span>
        <span className="tile-title">{title}</span>
        {detail && <span className="tile-detail">{phrases(detail)}</span>}
        <span className="tile-cta">{phrases(`${blocked ? 'Commentary only' : coverage(match)} · Hear it called, sound on →`)}</span>
      </span>
    </button>
    {/* A sibling, not inside the button: a link can't sit inside another control. */}
    {blocked && <a className="tile-yt" href={watchUrl(match)} target="_blank" rel="noopener noreferrer">Watch highlights on YouTube ↗</a>}
    {/* #163: top right, clear of the sport label on the left (below the YouTube link when both show); inline as App.css is #153's */}
    {match.peak_idx !== undefined && (
      <button className="tile-yt" style={{ top: blocked ? 50 : 12, cursor: 'pointer', background: 'rgba(6, 8, 15, .94)', boxShadow: '0 1px 8px rgba(0, 0, 0, .6)' }} onClick={() => onJump(match)}
        aria-label={`Jump to the big moment of ${title}`}>Jump to the big moment</button>
    )}
    </div>
  )
}
