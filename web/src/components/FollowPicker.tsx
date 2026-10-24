import { useEffect, useState } from 'react'
import { answerFor, cutAt, search, type Asked, type Player } from '../follow'

interface Props {
  replayKey: number // the list belongs to its replay
  momentIdx: number | null // the moment on screen: who has been named so far
  load: (at: number) => Promise<Player[]>
  onFollow: (name: string, roster: string[]) => void // the roster tells two Martínez apart
}

// "Follow a player" (#140): a search box over everyone in the match, those named so far first.
export function FollowPicker({ replayKey, momentIdx, load, onFollow }: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [got, setGot] = useState<Asked<Player[]> | null>(null)
  const at = cutAt(momentIdx)
  const players = answerFor(got, replayKey, '', at)

  useEffect(() => {
    if (!open) return
    let live = true
    const done = (value: Player[] | 'error') => live && setGot({ replay: replayKey, name: '', momentIdx: at, value })
    load(at).then(done, () => done('error'))
    return () => { live = false }
  }, [open, replayKey, at, load])

  const hits = Array.isArray(players) ? search(players, query) : []
  const pick = (name: string) => {
    setQuery('')
    setOpen(false)
    onFollow(name, Array.isArray(players) ? players.map((p) => p.name) : [])
  }
  return (
    <section className="panel glass follow" aria-label="Follow a player">
      <div className="panel-h"><h3>Follow</h3></div>
      <form className="ask" onSubmit={(e) => { e.preventDefault(); if (hits[0]) pick(hits[0].name) }}>
        <label className="sr-only" htmlFor="follow-q">Follow a player</label>
        <input id="follow-q" value={query} autoComplete="off" enterKeyHint="go" placeholder="Follow a player…"
          role="combobox" aria-expanded={open} aria-controls="follow-list"
          onFocus={() => setOpen(true)} onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)} />
      </form>
      {open && (
        players === 'loading' ? <p className="hint"><span className="spin sm" /> Loading players…</p>
          : players === 'error' ? <p className="err-text" role="alert">Couldn't load the players.</p>
          : hits.length === 0 ? <p className="hint">Nobody by that name in this match.</p>
          : (
            <ul id="follow-list" className="follow-list" aria-label="Players">
              {hits.map((p) => (
                <li key={p.name}>
                  <button type="button" onClick={() => pick(p.name)}>
                    <span>{p.name}</span>
                    <span className="label">{p.team ?? ''}{p.named ? ' · tonight' : ''}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
      )}
    </section>
  )
}
