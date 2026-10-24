import { momentTag } from '../moment'
import { embeds, posterUrl, showNoVideoCaption, watchUrl } from '../player'
import { commentatorName } from '../teams'
import { SPORT_NAMES, type Line, type Match, type Sport } from '../types'
import { onScreen, type Clock, type ReplayState } from '../useReplay'
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
  voice: { status: VoiceStatus; name: string; speaking: boolean }
  video: VideoState
  onVideo: (state: VideoState) => void
  onClock: (clock: Clock | null) => void
  onSport: (sport: Sport) => void
  onNext: (() => void) | null // the wall's next match (A-6.5), when there is more than one
  onVoiceSheet: () => void
  onFix: (line: Line) => void
  onRetry: () => void
  onReconnect: () => void
  onGo: (screen: Screen) => void
}

// The live page (docs/design.md "Layout"; PRD v5 R-6): the highlights fill the stage; over them the nav,
// the score bar and ON AIR pill, the moment tag and subtitle, the dock and the video timeline; the Lines
// and Proof cards stand in a glass column on the right (under the stage below 1100px).
export function Live(props: Props) {
  const { match, replay, replayKey, switching, sports, voice, video, onVideo, onClock, onSport, onNext, onVoiceSheet, onFix, onRetry, onReconnect, onGo } = props
  const shown = onScreen(replay)
  const moment = shown.moments.at(-1) ?? null
  const latest = shown.lines.find((l) => !replay.late.includes(l.line_id))
  const busy = replay.phase !== 'live'
  const gated = !!match.youtube_id
  // The owner blocks embedding: a still poster and a YouTube link, never the player's error screen.
  const blocked = gated && !embeds(match)
  const voiceLabel = commentatorName(voice.name)

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
  const fix = latest ? replay.fixes[latest.line_id] : undefined
  const latestMoment = latest ? shown.moments.find((m) => m.idx === latest.moment_idx) : undefined

  return (
    <div className="live">
      <div id="video" className={video === 'unavailable' && !busy ? 'off' : dim ? 'dim' : undefined}>
        {blocked && <img className="still" alt="" src={posterUrl(match.youtube_id!)} />}
        {replay.phase === 'live' && <VideoStage key={replayKey} youtubeId={blocked ? undefined : match.youtube_id} start={match.video_start ?? 0} onClock={onClock} onState={onVideo} />}
      </div>
      <section className="stage" aria-label={`${match.title ?? match.match_id} highlights`}>
        <div className="shade" />
        <Nav current="live" onGo={onGo} />
        <div className="lane hud">
          <ScoreBar match={match} moment={moment} moments={shown.moments} />
          <OnAir voice={voice} label={voiceLabel} />
        </div>
        {showNoVideoCaption(replay, video) && (blocked ? (
          <p className="novideo">Commentary only · <a href={watchUrl(match)} target="_blank" rel="noopener noreferrer">highlights on YouTube ↗</a></p>
        ) : (
          <p className="novideo">Highlights can't play here. Commentary carries on, timed to the replay.</p>
        ))}
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
        {replay.error && (
          <div className="banner"><div className="glass err" role="alert"><b />{replay.error}</div></div>
        )}
        {replay.phase === 'live' && video !== 'loading' && (
          latest ? (
            <div className={`lane subtitle${fix ? ' fixed' : ''}`} aria-live="polite" key={latest.line_id + (fix ? '-fixed' : '')}>
              {latestMoment && <span className={`tag${fix ? ' fixed' : ''}`}>{fix ? 'Fixed · ' : ''}{momentTag(latestMoment)}</span>}
              <p>{fix ? fix.corrected_text : latest.text}</p>
            </div>
          ) : (
            <div className="lane subtitle waiting" aria-live="polite"><p>Waiting for the first moment…</p></div>
          )
        )}
        <div className="lane dock">
          <div className="glass">
            <button className="btn back" aria-label="Back to the wall" onClick={() => onGo('wall')}>←<span> Wall</span></button>
            <div className="seg" role="group" aria-label="Sport">
              {sports.map((s) => (
                <button key={s} aria-pressed={match.sport === s} disabled={busy} onClick={() => s !== match.sport && onSport(s)}>
                  {SPORT_NAMES[s]}
                </button>
              ))}
            </div>
            <button className="btn voice" disabled={busy} aria-haspopup="dialog" onClick={onVoiceSheet}>
              <span>Voice: {voice.status === 'on' ? voice.name : voice.status === 'off' ? 'Off' : 'Unavailable'}</span>
            </button>
            {onNext && <button className="btn" disabled={busy} onClick={onNext}>Next match →</button>}
          </div>
        </div>
        {gated && <Timeline replay={replay} synced={video !== 'unavailable'} />}
        {overlay}
      </section>
      <aside className="side">
        <LineLog lines={shown.lines} late={replay.late} fixes={replay.fixes} moments={shown.moments} onFix={onFix} />
        <ProofPanel live={replay.stats} />
      </aside>
    </div>
  )
}

function OnAir({ voice, label }: { voice: Props['voice']; label: string }) {
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

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The video timeline (docs/design.md): the progress track with a marker per mapped moment, amber once
// called, and the player's time over the video's length.
function Timeline({ replay, synced }: { replay: ReplayState; synced: boolean }) {
  const length = replay.duration
  const marks = [...replay.moments, ...replay.queuedMoments].filter((m) => m.video_t !== undefined)
  const at = (t: number) => (length ? `${Math.min(100, (t / length) * 100)}%` : '0%')
  return (
    <div className="lane timeline">
      <span className="yt">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="1" y="3" width="14" height="10" rx="3" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <path d="M6.5 5.8v4.4L10.3 8z" fill="currentColor" />
        </svg>
        Broadcast highlights · YouTube · muted
      </span>
      <div className="track" aria-hidden>
        <span className="played" style={{ width: at(replay.now) }} />
        {marks.map((m) => (
          <span key={m.idx} className={`mk${m.video_t! <= replay.now ? ' done' : ''}`} style={{ left: at(m.video_t!) }} />
        ))}
      </div>
      <span className="clockline">
        <span className="sync">{synced ? 'Synced to video' : 'Replay clock'}</span>
        <span className="num">{mmss(replay.now)}{length ? ` / ${mmss(length)}` : ''}</span>
      </span>
    </div>
  )
}
