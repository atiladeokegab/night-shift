import { calledPlayer, clockText, momentName } from '../moment'
import { cricketScore, matchTeams } from '../teams'
import type { Match, Moment } from '../types'

// The broadcast lower third over the picture when the commentator calls a moment: its clock, player, event
// and the score after it, all from the moment itself. Live keys it by the moment, so each call replays the
// CSS slide-in and its ~5 s hold; aria-hidden, as the spoken and captioned line already says it.
export function LowerThird({ match, moment, moments }: { match: Match; moment: Moment; moments: Moment[] }) {
  const after = score(match, moment, moments)
  return (
    <div className="l3 glass" aria-hidden data-testid="lower-third">
      <span className="l3-min num">{clockText(moment)}</span>
      <span className="l3-body">
        <span className="l3-name">{calledPlayer(moment)}</span>
        <span className="l3-sub"><span className="l3-ev">{momentName(moment)}</span>{after && <span className="num"> · {after}</span>}</span>
      </span>
    </div>
  )
}

function score(match: Match, m: Moment, moments: Moment[]): string {
  const s = m.score
  if ('home' in s) {
    const [home, away] = matchTeams(match)
    return `${home.code} ${s.home}–${s.away} ${away.code}`
  }
  if ('runs' in s) {
    const c = cricketScore(match, m, moments)
    return `${c.batting.code} ${c.score}`
  }
  return 'lap' in s ? `Lap ${s.lap}/${s.laps}` : ''
}
