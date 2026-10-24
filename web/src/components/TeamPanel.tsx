import { useEffect, useState } from 'react'
import { getTeams } from '../api'
import { formLine, gameLine } from '../teamfacts'
import type { Teams } from '../types'

// The Teams panel (#375): each side's recent form, the head-to-head and the squad's headline numbers,
// as of the match's start. Headings and lists, every line short enough to say aloud.
export function TeamFacts({ data }: { data: Teams }) {
  const [a, b] = data.teams
  const none = !data.teams.some((t) => t.form.length || t.squad.length || t.note) && !data.head_to_head.length
  if (none) return <p className="hint">No team facts for this match.</p>
  return (
    <>
      {data.teams.map((t) => (
        <section key={t.team} aria-labelledby={`team-${t.team.replace(/\W/g, '')}`}>
          <h3 id={`team-${t.team.replace(/\W/g, '')}`}>{t.team}</h3>
          <p>{!t.form.length && t.note ? t.note : formLine(t.team, t.form)}</p>
          {t.form.length > 0 && <ul>{t.form.map((g) => <li key={g.date + g.opponent}>{gameLine(g)}</li>)}</ul>}
          {t.squad.length > 0 && (
            <>
              <h4>Squad</h4>
              <ul>{t.squad.map((p) => <li key={p.name}>{p.name}: {p.headline}</li>)}</ul>
            </>
          )}
        </section>
      ))}
      {a && b && (
        <section aria-labelledby="team-h2h">
          <h3 id="team-h2h">Head to head</h3>
          {data.head_to_head.length
            ? <ul>{data.head_to_head.map((g) => <li key={g.date + g.opponent}>{a.team}: {gameLine(g)}</li>)}</ul>
            : <p>{a.team} and {b.team} have no earlier meetings on record.</p>}
        </section>
      )}
    </>
  )
}

export function TeamPanel({ sport, matchId }: { sport: string; matchId: string }) {
  const [got, setGot] = useState<{ key: string; data: Teams | 'error' } | null>(null)
  const key = `${sport}/${matchId}`
  useEffect(() => {
    let live = true
    getTeams(sport, matchId).then((data) => live && setGot({ key, data }), () => live && setGot({ key, data: 'error' }))
    return () => { live = false }
  }, [sport, matchId, key])
  const data = got?.key === key ? got.data : null
  return (
    <section className="panel glass teams" aria-label="Teams">
      <div className="panel-h"><h2 id="teams-h" tabIndex={-1}>Teams</h2></div>
      {!data ? <p className="hint" role="status">Loading teams…</p>
        : data === 'error' ? <p className="err-text" role="alert">Couldn't load the teams.</p>
        : <TeamFacts data={data} />}
    </section>
  )
}
