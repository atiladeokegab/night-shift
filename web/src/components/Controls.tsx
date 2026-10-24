import { useEffect, useState, type RefObject } from 'react'

interface Props {
  card: RefObject<HTMLElement | null> // the video card, for fullscreen
  paused: boolean
  canPlay: boolean // a player is ready to take play, pause and seek
  onToggle: () => void
  now: number // the replay clock, in video seconds
  duration: number
  marks: { t: number; done: boolean }[] // a marker per mapped moment, amber once called
  onSeek: (t: number) => void
  volume: number // the commentary voice, 0 to 1; the video stays muted
  muted: boolean
  onVolume: (volume: number, muted: boolean) => void
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The playback controls on the bottom edge of the video card (#132): play/pause, a scrubber on the replay
// clock, the commentary's mute and volume, and fullscreen. A seek only moves the picture: the replay reads
// the new time from the player's clock, so no line shows or speaks before its moment (A-6.4).
export function Controls({ card, paused, canPlay, onToggle, now, duration, marks, onSeek, volume, muted, onVolume }: Props) {
  const [full, setFull] = useState(false)
  useEffect(() => {
    const sync = () => setFull(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])
  const at = (t: number) => (duration ? `${Math.min(100, (t / duration) * 100)}%` : '0%')
  const silent = muted || volume === 0

  return (
    <div className="controls">
      <button className="ctl" disabled={!canPlay} aria-label={paused ? 'Play' : 'Pause'} onClick={onToggle}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          {paused ? <path d="M4.5 2.8v10.4L13 8z" fill="currentColor" />
            : <path d="M4 3h3v10H4zM9 3h3v10H9z" fill="currentColor" />}
        </svg>
      </button>
      <span className="num time">{mmss(now)}{duration ? ` / ${mmss(duration)}` : ''}</span>
      <div className="scrub">
        <div className="track" aria-hidden>
          <span className="played" style={{ width: at(now) }} />
          {marks.map((m, i) => <span key={i} className={`mk${m.done ? ' done' : ''}`} style={{ left: at(m.t) }} />)}
        </div>
        <input type="range" aria-label="Seek" min={0} max={duration || 1} step={0.1} value={Math.min(now, duration || 1)}
          disabled={!canPlay || !duration} aria-valuetext={mmss(now)} onChange={(e) => onSeek(Number(e.target.value))} />
      </div>
      <button className="ctl" aria-label={silent ? 'Unmute commentary' : 'Mute commentary'} aria-pressed={silent}
        onClick={() => onVolume(volume || 1, !silent)}>
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M2 6h3l4-3v10L5 10H2z" fill="currentColor" />
          {silent ? <path d="M11 6l4 4M15 6l-4 4" stroke="currentColor" strokeWidth="1.4" fill="none" />
            : <path d="M11.2 5.5a3.5 3.5 0 0 1 0 5M12.8 3.8a6 6 0 0 1 0 8.4" stroke="currentColor" strokeWidth="1.3" fill="none" />}
        </svg>
      </button>
      <input className="vol" type="range" aria-label="Commentary volume" min={0} max={1} step={0.05} value={silent ? 0 : volume}
        onChange={(e) => onVolume(Number(e.target.value), false)} />
      <button className="ctl" aria-label={full ? 'Exit fullscreen' : 'Fullscreen'}
        onClick={() => (full ? document.exitFullscreen() : card.current?.requestFullscreen())?.catch(() => {})}>
        <svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          {full ? <path d="M6 2v4H2M10 2v4h4M6 14v-4H2M10 14v-4h4" /> : <path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4" />}
        </svg>
      </button>
    </div>
  )
}
