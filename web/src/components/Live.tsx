import { useCallback, useEffect, useRef, useState } from 'react'
import { momentTag } from '../moment'
import { embeds, posterUrl, setPlaying, showNoVideoCaption, shownCaption, watchUrl, type Caption as CaptionData, type Transport } from '../player'
import { SPORT_NAMES, type Line, type Match, type Sport } from '../types'
import { onScreen, type Clock, type ReplayState } from '../useReplay'
import { Caption } from './Caption'
import { Controls } from './Controls'
import { LineLog } from './LineLog'
import { Nav, type Screen } from './Nav'
import { ProofPanel } from './ProofPanel'
import { ScoreBar } from './ScoreBar'
import { VideoStage, type VideoState } from './VideoStage'

export type VoiceStatus = 'on' | 'off' | 'unavailable'

interface Props {
  match: Match
  replay: ReplayState
  replayKey: number // changes with every started replay, so the video restarts with it
  switching: boolean // started from the sport switch: "Switching to cricket…"
  sports: Sport[] // the sports the server has matches for
  voice: { status: VoiceStatus; chip: string; speaking: boolean }
  video: VideoState
  onVideo: (state: VideoState) => void
  onClock: (clock: Clock | null) => void
  onSport: (sport: Sport) => void
  onNext: (() => void) | null // the wall's next match (A-6.5), when there is more than one
  onVoiceSheet: () => void
  onFix: (line: Line) => void
  onAsk: (question: string, momentIdx: number) => Promise<void>
  onRetry: () => void
  onReconnect: () => void
  onGo: (screen: Screen) => void
  // #131's side of the contract (App.tsx). Until App passes them, the caption is the newest line on screen,
  // pause stays local to the player, and the volume stays local to the controls.
  caption?: CaptionData | null
  paused?: boolean
  onPause?: () => void
  onPlay?: () => void
  volume?: number // the commentary voice, 0 to 1
  muted?: boolean
  onVolume?: (volume: number, muted: boolean) => void
}

// The live page (#132): a bounded 16:9 video card with the controls on its bottom edge and the caption card
// docked under it, the sport and match bar above it, and Lines and Proof in a scrollable sidebar (below 900px
// one column, with a tab bar for them). Only the score bug and the ON AIR pill sit on the picture.
export function Live(props: Props) {
  const { match, replay, replayKey, switching, sports, voice, video, onVideo, onClock, onSport, onNext, onVoiceSheet, onFix, onAsk, onRetry, onReconnect, onGo } = props
  const shown = onScreen(replay)
  const moment = shown.moments.at(-1) ?? null
  const busy = replay.phase !== 'live'
  const gated = !!match.youtube_id
  // The owner blocks embedding: a still poster and a YouTube link, never the player's error screen.
  const blocked = gated && !embeds(match)
  const voiceLabel = voice.chip // the dock chip's name, never a lone nationality

  // Play, pause and seek reach the player once it is ready; a new player starts playing.
  const card = useRef<HTMLElement>(null)
  const [transport, setTransport] = useState<Transport | null>(null)
  const [localPaused, setLocalPaused] = useState(false)
  const onTransport = useCallback((t: Transport | null) => {
    setTransport(t)
    setLocalPaused(false)
  }, [])
  const held = props.paused
  const paused = held ?? localPaused
  useEffect(() => {
    if (held !== undefined) transport?.[held ? 'pause' : 'play']()
  }, [held, transport])
  const toggle = () => {
    setPlaying(paused, transport, props)
    setLocalPaused(!paused)
  }
  const [localVolume, setLocalVolume] = useState({ volume: 1, muted: false })
  const volume = props.volume ?? localVolume.volume
  const muted = props.muted ?? localVolume.muted
  const onVolume = (v: number, m: boolean) => {
    setLocalVolume({ volume: v, muted: m })
    props.onVolume?.(v, m)
  }
  const [tab, setTab] = useState<'lines' | 'proof'>('lines')

  let overlay = null
  if (replay.phase === 'starting') {
    overlay = switching ? (
      <div className="overlay" aria-busy="true">
        <span className="spin" />Switching to {SPORT_NAMES[match.sport].toLowerCase()}…
        <span className="label">{match.title?.split(',')[0]} · {voiceLabel}</span>
      </div>
    ) : <div className="overlay" aria-busy="true"><span className="spin" />Starting replay…</div>
  } else if (replay.phase === 'failed') {
    overlay = (
      <div className="overlay" role="alert">
        <span>Couldn't start the replay.</span>
        <span className="actions">
          <button className="btn primary" onClick={onRetry}>Try again</button>
          <button className="btn" onClick={() => onGo('wall')}>Back to matches</button>
        </span>
      </div>
    )
  } else if (gated && video === 'loading') {
    overlay = <div className="overlay" aria-busy="true"><span className="spin" />Loading highlights…</div>
  }

  const dim = replay.stream !== 'ok' || busy || video === 'loading'
  // The caption: #131's question or answer, or a line the picture has reached (never one from later, A-6.4).
  const live = shown.lines.filter((l) => !replay.late.includes(l.line_id))
  const caption = shownCaption(props.caption, live.map((l) => l.text))
  const line = caption?.kind === 'line' ? live.find((l) => l.text === caption.text) : undefined
  const fix = line ? replay.fixes[line.line_id] : undefined
  const answer = caption?.kind === 'answer' ? replay.answers.find((a) => a.text === caption.text) : undefined
  const tagged = shown.moments.find((m) => m.idx === (line ?? answer)?.moment_idx) ?? (caption?.kind === 'line' ? undefined : moment)
  const marks = [...replay.moments, ...replay.queuedMoments].filter((m) => m.video_t !== undefined)
    .map((m) => ({ t: m.video_t!, done: m.video_t! <= replay.now }))
  const canPlay = !!transport && video === 'ok' && !busy

  return (
    <div className="live">
      <Nav current="live" onGo={onGo} />
      <div className="live-body">
        <main className="live-main">
          <div className="pickbar glass">
            <button className="btn back" aria-label="Back to the wall" onClick={() => onGo('wall')}>←<span> Wall</span></button>
            <div className="seg" role="group" aria-label="Sport">
              {sports.map((s) => (
                <button key={s} aria-pressed={match.sport === s} disabled={busy} onClick={() => s !== match.sport && onSport(s)}>
                  {SPORT_NAMES[s]}
                </button>
              ))}
            </div>
            <button className="btn voice" disabled={busy} aria-haspopup="dialog" onClick={onVoiceSheet}
              aria-label={`Voice: ${voice.status === 'on' ? voice.chip : voice.status === 'off' ? 'Off' : 'Unavailable'}`}>
              <span><span className="pre">Voice: </span>{voice.status === 'on' ? voice.chip : voice.status === 'off' ? 'Off' : 'Unavailable'}</span>
            </button>
            {onNext && <button className="btn" disabled={busy} onClick={onNext}>Next match →</button>}
          </div>
          <section className="vcard" ref={card} aria-label={`${match.title ?? match.match_id} highlights`}>
            {/* A tap on the picture plays or pauses it; the Play button is the keyboard's way in. */}
            <div className="frame" onClick={canPlay ? toggle : undefined}>
              <div id="video" className={video === 'unavailable' && !busy ? 'off' : dim ? 'dim' : undefined}>
                {blocked && <img className="still" alt="" src={posterUrl(match.youtube_id!)} />}
                {replay.phase === 'live' && <VideoStage key={replayKey} youtubeId={blocked ? undefined : match.youtube_id} start={match.video_start ?? 0}
                  onClock={onClock} onState={onVideo} onTransport={onTransport} />}
              </div>
              <div className="bug">
                <ScoreBar match={match} moment={moment} moments={shown.moments} />
                <OnAir voice={voice} label={voiceLabel} offAir={!!replay.error} />
              </div>
              {showNoVideoCaption(replay, video) && (blocked ? (
                <p className="novideo">Commentary only · <a href={watchUrl(match)} target="_blank" rel="noopener noreferrer">highlights on YouTube ↗</a></p>
              ) : (
                <p className="novideo">Highlights can't play here. Commentary carries on, timed to the replay.</p>
              ))}
              {overlay}
            </div>
            <Controls card={card} paused={paused} canPlay={canPlay} onToggle={toggle} now={replay.now} duration={replay.duration}
              marks={marks} onSeek={(t) => transport?.seek(t)} volume={volume} muted={muted} onVolume={onVolume} />
          </section>
          {replay.stream === 'reconnecting' && (
            <div className="banner"><div className="glass warn" role="alert"><b />Reconnecting to the replay…</div></div>
          )}
          {replay.stream === 'disconnected' && (
            <div className="banner">
              <div className="glass err" role="alert">
                <b />Stream disconnected. Lines may be missing.
                <button className="btn sm" onClick={onReconnect}>Reconnect</button>
              </div>
            </div>
          )}
          {replay.phase === 'live' && video !== 'loading' && (
            replay.error ? (
              // A calm state whatever the server sent: the error payload goes to the console only.
              <Caption caption={null}>
                <div className="cap-state" role="status">
                  <p>Commentator is off air for a moment</p>
                  <button className="btn sm" onClick={onRetry}>Retry</button>
                </div>
              </Caption>
            ) : caption ? (
              <Caption caption={fix ? { ...caption, text: fix.corrected_text } : caption} fixed={!!fix}
                tag={tagged ? momentTag(tagged) : undefined} asked={answer?.question} />
            ) : (
              <Caption caption={null}><p className="cap-state" aria-live="polite">Waiting for the first moment…</p></Caption>
            )
          )}
        </main>
        <aside className="side" aria-label="Lines and proof">
          <div className="tabs" role="tablist" aria-label="Lines and proof">
            <button role="tab" id="tab-lines" aria-controls="pane-lines" aria-selected={tab === 'lines'} onClick={() => setTab('lines')}>Lines</button>
            <button role="tab" id="tab-proof" aria-controls="pane-proof" aria-selected={tab === 'proof'} onClick={() => setTab('proof')}>Proof</button>
          </div>
          <div className="pane lines-pane" role="tabpanel" id="pane-lines" aria-labelledby="tab-lines" data-on={tab === 'lines'}>
            <LineLog lines={shown.lines} late={replay.late} fixes={replay.fixes} moments={shown.moments} onFix={onFix}
              answers={replay.answers} onAsk={moment ? (q) => onAsk(q, moment.idx) : null} />
          </div>
          <div className="pane" role="tabpanel" id="pane-proof" aria-labelledby="tab-proof" data-on={tab === 'proof'}>
            <ProofPanel live={replay.stats} />
          </div>
        </aside>
      </div>
    </div>
  )
}

function OnAir({ voice, label, offAir }: { voice: Props['voice']; label: string; offAir: boolean }) {
  if (offAir) {
    return (
      <span className="onair glass off" role="status">
        <span className="rec" />OFF AIR
        <span className="who">{label}</span>
      </span>
    )
  }
  if (voice.status !== 'on') {
    return (
      <span className="onair glass">
        <span className="rec" />
        {voice.status === 'off' ? 'VOICE OFF' : 'VOICE UNAVAILABLE'}
        <span className="who">{voice.status === 'off' ? 'Subtitles only' : 'Subtitles carry on'}</span>
      </span>
    )
  }
  return (
    <span className={`onair glass${voice.speaking ? ' on' : ''}`} role="status">
      <span className="rec" />ON AIR
      <span className="bars" aria-hidden><span /><span /><span /><span /></span>
      <span className="who">{label}</span>
    </span>
  )
}
