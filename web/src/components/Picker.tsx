import { useState } from 'react'
import { cardArt } from '../art'
import { CARD_COPY, commentatorName, defaultVoice, matchTeams, teamStyle, voiceName } from '../teams'
import { SPORT_NAMES, type Match, type Voice } from '../types'
import { Nav, type Screen } from './Nav'

const SPEEDS: [number, string][] = [[1, 'Real time'], [4, '4x'], [16, '16x']]

interface Props {
  matches: Match[] | null // null while loading
  error: boolean
  voices: Voice[]
  onRetry: () => void
  onStart: (match: Match, speed: number) => void
  onGo: (screen: Screen) => void
}

// The match picker (docs/design.md "Screens"): one card per match, a speed choice, "Start replay →".
export function Picker({ matches, error, voices, onRetry, onStart, onGo }: Props) {
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
        <div className="cards" aria-hidden><div className="card ghost" /><div className="card ghost" /></div>
      </>
    )
  } else if (matches.length === 0) {
    body = <div className="notice glass">No matches yet. Load the demo data, then refresh.</div>
  } else {
    body = <div className="cards">{matches.map((m) => <Card key={m.match_id} match={m} voices={voices} onStart={onStart} />)}</div>
  }
  return (
    <div className="page">
      <Nav current="picker" onGo={onGo} />
      <main className="wrap">
        <p className="eyebrow">A live AI commentator for matches nobody calls.</p>
        <h1>Pick a match</h1>
        {body}
        <p className="foot">
          Match data: StatsBomb open data, Cricsheet, NBA play-by-play (stats.nba.com) and OpenF1. Highlights on
          YouTube, embedded and muted: the NBA channel, and fan uploads of the TV coverage of the 2022 World Cup final,
          Chelsea v Tottenham, India v Pakistan and the 2024 São Paulo Grand Prix. Commentary is AI-generated.
        </p>
      </main>
    </div>
  )
}

function Card({ match, voices, onStart }: { match: Match; voices: Voice[]; onStart: Props['onStart'] }) {
  // YouTube plays at most 2x, so with a highlights video only real time keeps lines in step with the
  // picture (#33; docs/design.md leaves 4x and 16x open).
  const [speed, setSpeed] = useState(match.youtube_id ? 1 : 4)
  const copy = CARD_COPY[match.match_id]
  const [home, away] = copy?.crest ? [teamStyle(copy.crest), null] : matchTeams(match)
  const title = copy?.title ?? match.title?.split(',')[0] ?? match.match_id
  const detail = copy?.detail ?? match.title?.split(',').slice(1).join(',').trim()
  const voice = voiceName(defaultVoice(voices, match.sport))
  return (
    <article className="card">
      <div className="art" dangerouslySetInnerHTML={{ __html: cardArt(match.sport, home, away) }} />
      <div className="card-body">
        <span className="label">{SPORT_NAMES[match.sport]}</span>
        <h2>{title}</h2>
        {detail && (
          <p className="detail">
            {detail.split(' · ').map((part, i) => <span key={i}>{i > 0 && ' · '}<span className="nw">{part}</span></span>)}
          </p>
        )}
        {copy && <p className="result">{copy.result}</p>}
        <div className="meta">{voice && <span className="voice">{commentatorName(voice)}</span>}</div>
        <div className="chips speeds" role="radiogroup" aria-label="Speed">
          {SPEEDS.filter(([value]) => !match.youtube_id || value === 1).map(([value, name]) => (
            <label key={value} title={match.youtube_id ? 'The highlights play in real time' : undefined}>
              <input type="radio" name={`speed-${match.match_id}`} checked={speed === value} onChange={() => setSpeed(value)} />
              <span>{name}</span>
            </label>
          ))}
        </div>
        <button className="btn primary" onClick={() => onStart(match, speed)}>
          Start replay <span className="arr" aria-hidden>→</span>
        </button>
      </div>
    </article>
  )
}
