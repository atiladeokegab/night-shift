import { useEffect, useState } from 'react'
import { getStats } from '../api'
import type { Stats } from '../types'
import { Nav, type Screen } from './Nav'

// The About page. It claims nothing the README doesn't.
export function About({ onGo }: { onGo: (screen: Screen) => void }) {
  const [stats, setStats] = useState<Stats | null>(null)
  useEffect(() => { getStats().then(setStats, () => setStats(null)) }, []) // no cost figure is better than a stuck page
  const perMatch = stats?.cost_per_match_usd
  return (
    <div className="page">
      <Nav current="about" onGo={onGo} />
      <main className="wrap">
        <p className="eyebrow">About Touchline</p>
        <h1>The describer that checks itself.</h1>
        <div className="about">
          <p>
            <strong>Most matches are streamed with nobody describing them.</strong> Touchline describes them. As each
            key moment plays, it calls it in one short line, read aloud and shown as a large caption, never before the
            moment reaches the picture. The matches here are replays of real matches, as if live.
          </p>
          <p>
            <strong>It checks the score, the leader and the key numbers before it speaks.</strong> Before a call is spoken, its score, who leads,
            the margin and the players' counts are checked against the match data. A call that fails is tried once
            more; if that fails too, a line built from the data is spoken instead and a producer sees the call. The
            analyst's stat lines and the answers to fans' questions get the same check; one still wrong after its retry
            is dropped, never said.
          </p>
          <p>
            <strong>One describer, four sports.</strong> The same agent, with the same prompt, describes football,
            cricket, basketball and F1. It reads the match's real event data and never sees anything from later in the
            match than the moment it is calling.
          </p>
          <p>
            <strong>Each fix that passes the check is recorded as training data.</strong> A producer can fix any
            line, and each fix that passes the number check is recorded in Mubit as training data for a smaller
            describer; fixes to the analyst's stat lines are left out. No version has passed
            Mubit's test yet, so we make no claim for it.
          </p>
          {/* #246: what a match costs to describe, measured live (GET /stats, #174); moved from the home page */}
          {typeof perMatch === 'number' && (
            <p>
              A full replay, mostly highlights, costs ${perMatch.toFixed(2)} on average. A whole match calls every moment, so it
              costs more.
            </p>
          )}
        </div>
        <p className="foot">
          Match data: StatsBomb open data (football), Cricsheet (cricket), NBA play-by-play (basketball) and OpenF1
          timing (F1). Video: broadcast highlights on YouTube, embedded and muted where their owners allow it, linked
          where they don't. Commentary is AI-generated.
        </p>
      </main>
    </div>
  )
}
