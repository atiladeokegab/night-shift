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
            <strong>For matches streamed without audio description, Touchline describes the action.</strong> As each
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
            describer; fixes to the analyst's stat lines are left out. The app does not call
            an adapter, so we make no claim for it.
          </p>
          {/* #246: what a match costs to describe, measured live (GET /stats, #174); moved from the home page */}
          {typeof perMatch === 'number' && (
            <p>
              A full replay, mostly highlights, costs ${perMatch.toFixed(2)} on average. A whole match calls every moment, so it
              costs more.
            </p>
          )}
        </div>
        {/* Facts from agent/prompt.md, agent/analyst.md and the pacing in core/replay.py and core/insight.py */}
        <section className="about how" aria-labelledby="how-h">
          <h2 id="how-h">How the two commentators work</h2>
          <ul>
            <li>
              <strong>The lead calls each moment.</strong> One line of at most 20 words: a goal, a wicket or an
              overtake with rising excitement, a routine moment calmly and briefly.
            </li>
            <li>
              <strong>The analyst adds a stat between moments.</strong> In the quiet before the next moment, one
              point from a stat in about 12 to 18 words; the lead comes back with a few words or one short question.
            </li>
            <li>
              <strong>What they see.</strong> The match's event data, the score or standing and the recent play,
              never anything later than the moment. Neither sees the video unless you share the tab with Let
              them watch: then a short note of what the picture shows goes into the next line, and the frame is
              never stored.
            </li>
            <li>
              <strong>How they hand over.</strong> They take turns, never one twice in a row, each starting as the
              other has likely finished. A quiet stretch takes at most four turns, and a line starts only with
              about 3 seconds of room before the next moment. A match with no video waits out the gaps between
              moments, never longer than 8 seconds.
            </li>
          </ul>
          <svg className="glass flow" viewBox="0 0 340 452" role="img" aria-labelledby="flow-t">
            <title id="flow-t">
              Match data goes to the lead and the analyst. Each line passes the number check, or gets one retry and
              then a line from the data. It is voiced by ElevenLabs and stored for replays. A producer's fix goes to
              Mubit's Score check training.
            </title>
            <defs>
              <marker id="flow-a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
                <path d="M0 0 8 4 0 8z" className="tip" />
              </marker>
            </defs>
            <rect x="20" y="16" width="300" height="40" rx="10" />
            <text x="170" y="41">Match data: events, score, recent play</text>
            <path d="M90 56v24" />
            <path d="M250 56v24" />
            <rect x="20" y="86" width="140" height="40" rx="10" />
            <text x="90" y="111">Lead: the call</text>
            <rect x="180" y="86" width="140" height="40" rx="10" />
            <text x="250" y="111">Analyst: a stat</text>
            <path d="M90 126v24" />
            <path d="M250 126v24" />
            <rect x="20" y="156" width="300" height="40" rx="10" className="key" />
            <text x="170" y="181">Number check: score, leader, numbers</text>
            <path d="M170 196v24" />
            <rect x="20" y="226" width="300" height="52" rx="10" className="alt" />
            <text x="170" y="248">If wrong: one retry, then a line</text>
            <text x="170" y="267">from the data (a stat is dropped)</text>
            <path d="M170 278v24" />
            <rect x="20" y="308" width="300" height="40" rx="10" />
            <text x="170" y="333">ElevenLabs voice, and a caption</text>
            <path d="M90 348v24" />
            <path d="M250 348v24" />
            <rect x="20" y="378" width="140" height="56" rx="10" />
            <text x="90" y="402">Stored, reused</text>
            <text x="90" y="421">on replays</text>
            <rect x="180" y="378" width="140" height="56" rx="10" className="key" />
            <text x="250" y="402">Producer's fix: Mubit</text>
            <text x="250" y="421">Score check training</text>
          </svg>
          <p>
            <a href="/stats">The live figures behind the Proof card</a> (JSON, from GET /stats).
          </p>
        </section>
        <p className="foot">
          Match data: StatsBomb open data (football), Cricsheet (cricket), NBA play-by-play (basketball) and OpenF1
          timing (F1). Video: broadcast highlights on YouTube, embedded and muted where their owners allow it, linked
          where they don't. Commentary is AI-generated.
        </p>
      </main>
    </div>
  )
}
