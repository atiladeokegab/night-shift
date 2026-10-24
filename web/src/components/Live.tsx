import { useCallback, useEffect, useRef, useState } from 'react'
import { clockText, momentTag } from '../moment'
import { embeds, posterUrl, setPlaying, showNoVideoCaption, shownCaption, watchUrl, type Transport } from '../player'
import type { Caption as CaptionData } from '../turns'
import { SPORT_NAMES, type Line, type Match, type Sport } from '../types'
import { onScreen, type Clock, type ReplayState } from '../useReplay'
import type { Player, Profile } from '../follow'
import { latestShooter, MAPPED, pickedFor, type Picked, type Shots } from '../shots'
import { CARD_COPY, matchTeams } from '../teams'
import { Caption } from './Caption'
import { Controls } from './Controls'
import { FollowPicker } from './FollowPicker'
import { LineLog } from './LineLog'
import { Nav, type Screen } from './Nav'
import { ProfileCard } from './ProfileCard'
import { ProofPanel } from './ProofPanel'
import { ScoreBar } from './ScoreBar'
import { ShotMap } from './ShotMap'
import { VideoStage, type VideoState } from './VideoStage'

export type VoiceStatus = 'on' | 'off' | 'unavailable'

interface Props {
  match: Match
  replay: ReplayState
  replayKey: number // changes with every started replay, so the video restarts with it
  switching: boolean // started from the sport switch: "Switching to cricket…"
  sports: Sport[] // the sports the server has matches for
  voice: { status: VoiceStatus; chip: string; speaking: boolean; analyst?: string }
  video: VideoState
  onVideo: (state: VideoState) => void
  onClock: (clock: Clock | null) => void
  onSport: (sport: Sport) => void
  onNext: (() => void) | null // the wall's next match (A-6.5), when there is more than one
  onVoiceSheet: () => void
  onFix: (line: Line) => void
  onAsk: (question: string, momentIdx: number) => Promise<void>
  onShots: (name: string, momentIdx: number) => Promise<Shots | null>
  onPlayers: (at: number) => Promise<Player[]> // #140: everyone in the match so far
  onProfile: (name: string, momentIdx: number) => Promise<Profile | null>
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
  const { match, replay, replayKey, switching, sports, voice, video, onVideo, onClock, onSport, onNext, onVoiceSheet, onFix, onAsk, onShots, onPlayers, onProfile, onRetry, onReconnect, onGo } = props
  const shown = onScreen(replay)
  const moment = shown.moments.at(-1) ?? null
  const busy = replay.phase !== 'live'
  const gated = !!match.youtube_id
  // The owner blocks embedding: a still poster and a YouTube link, never the player's error screen.
  const blocked = gated && !embeds(match)
  const voiceLabel = voice.chip // the dock chip's name, never a lone nationality
  // The shot map follows the moment on screen while it is open (#120).
  const [picked, setPicked] = useState<Picked>(null)
  const mapOf = pickedFor(picked, replayKey)
  const mapped = MAPPED.includes(match.sport)
  const shooter = mapped ? latestShooter(shown.moments) : null
  const openMap = (name: string) => setPicked({ name, replay: replayKey })
  // The followed player (#140) belongs to its replay, like the map: their lines stand out, the map pins to them.
  const [follow, setFollow] = useState<(Picked & { roster: string[] }) | null>(null)
  const followed = pickedFor(follow, replayKey)
  const roster = followed ? follow!.roster : []
  const mapFor = followed ?? shooter

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
  const [chosenTab, setTab] = useState<'follow' | 'lines' | 'proof' | 'shots'>('lines')
  const tab = chosenTab === 'shots' && !mapped ? 'lines' : chosenTab // a sport with no shot map shows Lines

  const ended = fullTime(replay, video)
  const score = finalScore(match, shown.moments.at(-1))
  const fullTimeText = `Full time${score ? ` · ${score}` : ''}`
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
  } else if (ended) {
    overlay = (
      <div className="overlay end" role="status">
        <span>{fullTimeText}</span>
        <span className="actions">
          <button className="btn primary" onClick={onRetry}>Watch again</button>
          {onNext && <button className="btn" onClick={onNext}>Next match →</button>}
        </span>
      </div>
    )
  }

  const dim = replay.stream !== 'ok' || busy || video === 'loading'
  // The caption: App's question or answer, or a line the picture has reached (never one from later, A-6.4),
  // in its fixed wording once a producer fixed it.
  const live = shown.lines.filter((l) => !replay.late.includes(l.line_id))
  const said = (l: Line) => replay.fixes[l.line_id]?.corrected_text ?? l.text
  // A question waits in the caption's header; it and its answer take the caption once the answer speaks (#153).
  const pending = props.caption?.kind === 'question' ? props.caption.text.replace(/^A viewer asks:\s*/, '') : undefined
  const caption = shownCaption(pending === undefined ? props.caption : null, live.map(said))
  const line = caption?.kind === 'line' ? live.find((l) => said(l) === caption.text) : undefined
  const answer = caption?.kind === 'answer' ? replay.answers.find((a) => a.text === caption.text) : undefined
  const tagged = shown.moments.find((m) => m.idx === (line ?? answer)?.moment_idx) ?? (caption?.kind === 'line' ? undefined : moment)
  const marks = [...replay.moments, ...replay.queuedMoments].filter((m) => m.video_t !== undefined)
    .map((m) => ({ t: m.video_t!, done: m.video_t! <= replay.now }))
  const canPlay = !!transport && video === 'ok' && !busy
  const noVideo = !gated || blocked || video === 'unavailable'
  const title = CARD_COPY[match.match_id]?.title ?? match.title?.split(',')[0] ?? match.match_id
  const speaker = caption?.speaker ?? line?.speaker
  const onAirLabel = speaker === 'analyst' ? ['Analyst', voice.analyst].filter(Boolean).join(' · ') : voiceLabel && `Lead · ${voiceLabel}`
  const first = replay.queuedMoments.reduce<typeof moment>((a, m) => (a && (a.video_t ?? 0) <= (m.video_t ?? 0) ? a : m), null)

  return (
    <div className="live">
      <Nav current="live" onGo={onGo}>
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
            {onNext && <button className="btn next" disabled={busy} aria-label="Next match" onClick={onNext}><span>Next match </span>→</button>}
          </div>
      </Nav>
      <div className="live-body">
        <main className="live-main">
          <section className="vcard" ref={card} aria-label={`${match.title ?? match.match_id} highlights`} data-video={noVideo ? 'off' : undefined}>
            {/* A tap on the picture plays or pauses it; the Play button is the keyboard's way in. */}
            <div className="frame" onClick={canPlay ? toggle : undefined}>
              <div id="video" className={video === 'unavailable' && !busy ? 'off' : dim ? 'dim' : undefined}>
                {blocked && <img className="still" alt="" src={posterUrl(match.youtube_id!)} />}
                {replay.phase === 'live' && <VideoStage key={replayKey} youtubeId={blocked ? undefined : match.youtube_id} start={match.video_start ?? 0}
                  onClock={onClock} onState={onVideo} onTransport={onTransport} />}
              </div>
              <div className="bug">
                <ScoreBar match={match} moment={moment} moments={shown.moments} />
                <OnAir voice={voice} label={onAirLabel} offAir={!!replay.error} onOpen={busy ? undefined : onVoiceSheet} />
              </div>
              {showNoVideoCaption(replay, video) && (blocked ? (
                <p className="novideo">Commentary only · <a href={watchUrl(match)} target="_blank" rel="noopener noreferrer">highlights on YouTube ↗</a></p>
              ) : (
                <p className="novideo">Highlights can't play here. Commentary carries on, timed to the replay.</p>
              ))}
              {overlay}
            </div>
            <Controls card={card} paused={paused || ended} canPlay={canPlay} onToggle={ended ? onRetry : toggle} now={replay.duration ? Math.min(replay.now, replay.duration) : replay.now} duration={replay.duration}
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
            ) : ended ? (
              // Full time replaces the last play; the overlay above holds Watch again (#153).
              <Caption caption={null}><p className="cap-text">{fullTimeText}</p></Caption>
            ) : caption ? (
              <Caption caption={{ ...caption, speaker }} fixed={!!line && !!replay.fixes[line.line_id]} offAir={answer?.off_air}
                tag={tagged ? momentTag(tagged) : undefined} asked={answer?.question} pending={pending} title={title} />
            ) : (
              <Caption caption={null}>
                <p className="cap-state" aria-live="polite">
                  {first?.video_t !== undefined ? `First call in ${mmss(first.video_t - replay.now)}` : first ? `First call at ${clockText(first)}` : 'Waiting for the first moment…'}
                </p>
              </Caption>
            )
          )}
        </main>
        <aside className="side" aria-label="Lines and proof">
          <div className="tabs" role="tablist" aria-label="Lines and proof">
            <button role="tab" id="tab-follow" aria-controls="pane-follow" aria-selected={tab === 'follow'} onClick={() => setTab('follow')}>Follow</button>
            <button role="tab" id="tab-lines" aria-controls="pane-lines" aria-selected={tab === 'lines'} onClick={() => setTab('lines')}>Lines</button>
            <button role="tab" id="tab-proof" aria-controls="pane-proof" aria-selected={tab === 'proof'} onClick={() => setTab('proof')}>Proof</button>
            {mapped && <button role="tab" id="tab-shots" aria-controls="pane-shots" aria-selected={tab === 'shots'} onClick={() => setTab('shots')}>Shot map</button>}
          </div>
          <div className="pane" role="tabpanel" id="pane-follow" aria-labelledby="tab-follow" data-on={tab === 'follow'}>
            {followed ? (
              moment ? <ProfileCard name={followed} replayKey={replayKey} momentIdx={moment.idx} load={onProfile}
                onShots={mapped ? openMap : null} onUnfollow={() => setFollow(null)} />
                : <section className="panel glass"><p className="hint">Following {followed}: the card shows with the first moment.</p></section>
            ) : (
              <FollowPicker replayKey={replayKey} momentIdx={moment?.idx ?? null} load={onPlayers} onFollow={(name, roster) => setFollow({ name, replay: replayKey, roster })} />
            )}
          </div>
          <div className="pane lines-pane" role="tabpanel" id="pane-lines" aria-labelledby="tab-lines" data-on={tab === 'lines'}>
            <LineLog lines={shown.lines} late={replay.late} fixes={replay.fixes} moments={shown.moments} onFix={onFix}
              answers={replay.answers} onAsk={moment ? (q) => onAsk(q, moment.idx) : null} shooter={null} onShots={openMap} followed={followed} roster={roster} onUnfollow={() => setFollow(null)} />
          </div>
          <div className="pane" role="tabpanel" id="pane-proof" aria-labelledby="tab-proof" data-on={tab === 'proof'}>
            <ProofPanel live={replay.stats} />
          </div>
          {mapped && (
            <div className="pane" role="tabpanel" id="pane-shots" aria-labelledby="tab-shots" data-on={tab === 'shots'}>
              <section className="panel glass shots-card" aria-label="Shot map">
                <h3>Shot map</h3>
                {mapFor ? <button className="btn sm" onClick={() => openMap(mapFor)}>Shot map · {mapFor}</button>
                  : <p className="hint">Opens with the first shot on screen.</p>}
              </section>
            </div>
          )}
        </aside>
      </div>
      {mapOf && moment && <ShotMap key={replayKey} name={mapOf} momentIdx={moment.idx} load={onShots} onClose={() => setPicked(null)} />}
    </div>
  )
}

const mmss = (s: number) => {
  const t = Math.max(0, Math.ceil(s))
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`
}

// The replay is over once the stream has ended and the picture has reached everything it sent.
function fullTime(replay: ReplayState, video: VideoState): boolean {
  if (!replay.ended || replay.phase !== 'live' || replay.queuedMoments.length || replay.queuedLines.length) return false
  return video !== 'ok' || !replay.duration || replay.now >= replay.duration - 2
}

// "CHE 2–2 TOT" (or "ARG 3–3 FRA · pens 4–2") from the last moment on screen; a race or an innings has no such line, so the card's result.
function finalScore(match: Match, last: ReplayState['moments'][number] | undefined): string {
  const s = last?.score
  if (s && 'home' in s) {
    const [home, away] = matchTeams(match)
    const pens = last?.detail.shootout as { home: number; away: number } | undefined
    return `${home.code} ${s.home}–${s.away} ${away.code}${pens ? ` · pens ${pens.home}–${pens.away}` : ''}`
  }
  return CARD_COPY[match.match_id]?.result ?? ''
}

function OnAir({ voice, label, offAir, onOpen }: { voice: Props['voice']; label: string; offAir: boolean; onOpen?: () => void }) {
  let cls = 'onair glass'
  let body
  if (offAir) {
    cls += ' off'
    body = <><span className="rec" />OFF AIR<span className="who">{label}</span></>
  } else if (voice.status !== 'on') {
    body = (
      <>
        <span className="rec" />
        {voice.status === 'off' ? 'VOICE OFF' : 'VOICE UNAVAILABLE'}
        <span className="who">{voice.status === 'off' ? 'Subtitles only' : 'Subtitles carry on'}</span>
      </>
    )
  } else {
    if (voice.speaking) cls += ' on'
    body = <><span className="rec" /><span className="lbl">ON AIR</span><span className="bars" aria-hidden><span /><span /><span /><span /></span><span className="who">{label}</span></>
  }
  const status = <span className="st" role={offAir || voice.status === 'on' ? 'status' : undefined}>{body}</span>
  if (!onOpen) return <span className={cls}>{status}</span>
  // A tap on the pill opens the voice sheet (the phone's bar has no voice button), never the play toggle under it.
  return (
    <button type="button" className={cls} aria-haspopup="dialog" onClick={(e) => (e.stopPropagation(), onOpen())}>
      {status}<span className="sr-only"> Voice settings</span>
    </button>
  )
}
