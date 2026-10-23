import type { Match, Sport, Voice } from '../types'
import type { ReplayState } from '../useReplay'
import type { useSpeech } from '../useSpeech'
import { LineLog } from './LineLog'
import { ScoreBar } from './ScoreBar'
import { VideoStage } from './VideoStage'

interface Props {
  match: Match
  replay: ReplayState
  replayKey: number // changes with every started replay, so the video restarts with it
  speech: ReturnType<typeof useSpeech>
  voices: Voice[]
  voiceId: string | null
  onVoice: (id: string) => void
  canSwitchTo: (sport: Sport) => boolean
  onSwitch: (sport: Sport) => void
  onRetry: () => void
  onReconnect: () => void
  onBack: () => void
}

// The live match page (PRD v2, R-6): score bar, controls, the highlights video with the subtitle
// under it, and the line log and proof panel beside it (stacked under 760px). Structure and wiring
// only: the new look waits for the lead's redesigned mockup (#21).
export function Live(props: Props) {
  const { match, replay, replayKey, speech, voices, voiceId, onVoice, canSwitchTo, onSwitch, onRetry, onReconnect, onBack } = props
  const moment = replay.moments.at(-1) ?? null
  const latest = replay.lines[0]
  const starting = replay.phase === 'starting'
  const label = match.title ?? match.match_id

  if (replay.phase === 'failed') {
    return (
      <main className="state">
        <p>Couldn't start the replay.</p>
        <div className="row">
          <button className="primary" onClick={onRetry}>Try again</button>
          <button onClick={onBack}>Back to matches</button>
        </div>
      </main>
    )
  }

  return (
    <main className="live">
      <ScoreBar match={match} moment={moment} />

      <div className="controls">
        <button onClick={onBack}>← Matches</button>
        <div className="tabs" role="group" aria-label="Sport">
          {(['football', 'cricket'] as Sport[]).map((s) => (
            <button key={s} className={s === match.sport ? 'on' : ''} aria-pressed={s === match.sport}
              disabled={starting || !canSwitchTo(s)} onClick={() => s !== match.sport && onSwitch(s)}>
              {s === 'football' ? 'Football' : 'Cricket'}
            </button>
          ))}
        </div>
        <button disabled={!speech.available} aria-pressed={speech.on} onClick={() => speech.setOn(!speech.on)}>
          {!speech.available ? 'Voice unavailable in this browser' : speech.on ? 'Voice on' : 'Voice off'}
        </button>
        {/* A-6.3@1: the voice is a setting; a change applies from the next line, no reload. */}
        <select aria-label="Commentator voice" value={voiceId ?? ''} disabled={!voices.length}
          onChange={(e) => onVoice(e.target.value)}>
          {voices.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <span className={`on-air${speech.speaking ? ' speaking' : ''}`} aria-live="off">
          <span className="bars" aria-hidden><i /><i /><i /></span>On air
        </span>
      </div>

      {replay.stream === 'reconnecting' && <p className="banner amber">Reconnecting to the replay…</p>}
      {replay.stream === 'disconnected' && (
        <p className="banner red">
          Stream disconnected. Lines may be missing. <button onClick={onReconnect}>Reconnect</button>
        </p>
      )}
      {replay.error && <p className="banner red">{replay.error}</p>}

      <div className="grid">
        <section className={`panel stage${replay.stream === 'reconnecting' ? ' dim' : ''}`}>
          <div className="stage-wrap">
            {starting ? <div className="video empty">Starting replay…</div>
              : <VideoStage key={replayKey} youtubeId={match.youtube_id} label={label} />}
          </div>
          <p className="subtitle" aria-live="assertive" key={latest?.line_id ?? 'waiting'}>
            {latest ? latest.text : 'Waiting for the first moment…'}
          </p>
        </section>
        <aside className="side">
          <LineLog lines={replay.lines} moments={replay.moments} />
          {/* #19 fills the proof panel. */}
          <section className="panel proof" aria-label="Proof">
            <h2>Proof</h2>
            <p className="muted">No lines yet.</p>
          </section>
        </aside>
      </div>
    </main>
  )
}
