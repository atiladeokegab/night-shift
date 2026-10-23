import { matchTeams, sides } from '../teams'
import type { Match, Sport } from '../types'
import type { ReplayState } from '../useReplay'
import type { useSpeech } from '../useSpeech'
import { Ground } from './Ground'
import { LineLog } from './LineLog'
import { ProofPanel } from './ProofPanel'
import { Pitch } from './Pitch'
import { ScoreBar } from './ScoreBar'

interface Props {
  match: Match
  replay: ReplayState
  speech: ReturnType<typeof useSpeech>
  canSwitchTo: (sport: Sport) => boolean
  onSwitch: (sport: Sport) => void
  onRetry: () => void
  onReconnect: () => void
  onBack: () => void
}

// The live match page (docs/design.md "Screens"): score bar, controls, the field with the subtitle
// under it, and the line log and proof panel beside it (stacked under 760px).
export function Live({ match, replay, speech, canSwitchTo, onSwitch, onRetry, onReconnect, onBack }: Props) {
  const moment = replay.moments.at(-1) ?? null
  const latest = replay.lines[0]
  const starting = replay.phase === 'starting'
  const [home, away] = matchTeams(match)
  const { ours, theirs } = moment ? sides(match, moment.team) : { ours: home, theirs: away }
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
          <div className="field-wrap">
            {match.sport === 'football'
              ? <Pitch moment={moment} ours={ours.color} theirs={theirs.color} label={label} />
              : <Ground moment={moment} bat={ours.color} field={theirs.color} label={label} />}
            {starting && <div className="overlay">Starting replay…</div>}
          </div>
          <p className="subtitle" aria-live="assertive" key={latest?.line_id ?? 'waiting'}>
            {latest ? latest.text : 'Waiting for the first moment…'}
          </p>
        </section>
        <aside className="side">
          <LineLog lines={replay.lines} moments={replay.moments} />
          <ProofPanel live={replay.stats} />
        </aside>
      </div>
    </main>
  )
}
