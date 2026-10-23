<!-- Generated from the team PRD (v3, changes C-001 and C-002, approved 2026-10-23). This copy is what every agent builds and reviews against; it is refreshed whenever the PRD changes. The model's input is event data; the highlights video is display only. -->

# night-shift: PRD v3

## Problem
Most matches in most sports are played with nobody calling them: grassroots and lower-league football, most of the women's game, club and county cricket. A clever model could commentate them, but it is too slow to call a moment while it is still on screen and too expensive to run for every moment of every match.

## Users
- Fan: follows a replayed match nobody commentates and hears each key moment called aloud, with subtitles, in about a second
- Producer: watches the same page and fixes a wrong line in one tap; the fix goes back through Mubit as training signal
- Judge: watches the 3-minute demo and the proof panel (latency, cost, lines, fixes, the adapter's result)
- Traffic runner (scripts/replay_matches.py): replays many real matches of both sports through the commentator so the Mubit task trains

## Goals
- **Train our own commentator model on Mubit tonight from real, varied calls**: Saturday is left for a second version trained on producer fixes. Measure: One Mubit task with 25+ kept examples from 8+ football and 8+ cricket matches before 00:00 UTC Saturday, checked in the console
- **Call each key moment in about a second, in either sport, with one agent**: The line lands while the moment is still on screen; one agent covers both sports. Measure: First word p50 <= 1.0 s and p95 <= 1.5 s at 10x replay speed
- **Show a correction becoming a model update, live**: Scores Mubit's 25% judging criterion directly. Measure: A producer fix on stage is stored, sent through the same Mubit task and session, and visible in the proof panel

## Principles
- Do in rank order (1..n, P0 -> P3); stop when time runs out: main is always demoable. Deliberate exception: R-1 (traffic) ranks above the spine because Mubit's training day resets at 00:00 UTC; it needs no server
- Conflict rule: when this PRD and the real data or merged code disagree, the data and the code win; keep the behaviour and say so in DONE
- One task: one system prompt, one message template, one tool set, one model; the sport goes in the message, never the system prompt
- Real traffic only: never padded, repeated or synthetic calls through Mubit (Mubit sees usage and judges whether it is real)
- Facts come from the feed through tools, never the model's memory of famous matches
- Tests come from the goal, not the sample data: held-out, adversarial and messy matches; every check is shown red on an injected defect before its green is believed
- Every done claim says Verified: and Not exercised:; known limitations are written as failures; no metric is stated that is not measured
- The demo runs from main's deployed URL; anything shown outside our product (Mubit's console) is said aloud as such

## Non-goals
- Video or vision input: the feed is event data
- A live real-world match feed: replays of real matches only
- A system prompt per sport, or a second commentator persona (splits the Mubit task)
- Sports beyond football and cricket, or any sport without real event data
- Our own fine-tuning or model hosting: Mubit trains the model
- Any claim that our model beats the big one: it matches it, at lower cost
- Unsourced statistics in the pitch; betting, odds or predictions

## Owner
Atilade (lead)

## Glossary
- **moment**: One key event in Moment shape (docs/CONTRACT.md): a StatsBomb event or a Cricsheet ball, picked by the moment picker
- **line**: One spoken commentary line for one moment, at most 20 words, with its latency, tokens and Mubit request ids
- **fix**: A producer's corrected line, stored beside the original and sent back through Mubit
- **task**: Mubit's unit of training: same system prompt, tools, tool choice, output format and model
- **session**: One match: metadata.user_id = match-<sport>-<id>

## Constraints
- Stack: `docs/stack.md`
- Tests run offline: yes
- Limit: make smoke runs offline from a fresh clone in under 2 minutes with no API keys (FakeProvider) (why: CI and builders have no Mubit key) (check: make smoke)
- Limit: At most one tool round per line; every model and tool call times out inside the moment's window, and a line that would land late is skipped and counted as late, never spoken late (why: A late line is about the past; a slow call must degrade cleanly) (check: tests/acceptance/test_A_3_3.py)
- Limit: Every network fetch (StatsBomb, Cricsheet, Mubit) has a timeout and downloaded data is cached and treated as untrusted (why: A hung fetch must not stall a replay or the traffic run) (check: tests/acceptance/test_A_1_1.py)
- Invariant: Every model call goes through Mubit (https://api.mubit.ai/anthropic, claude-haiku-4-5); none from the browser (why: The event rule, and the task Mubit trains) (check: tests/acceptance/test_A_1_2.py)
- Invariant: No moment's model input contains anything from later in the feed (why: Commentary must not know the future; keeps the eval honest) (check: tests/acceptance/test_A_1_4.py)
- Invariant: Held-out matches (sha256(sport:match_id) % 5 == 0) and the two demo matches never go through the traffic runner; the agreement eval and the stage side by side use only them (why: The adapter must not be scored on what it trained on (propadm.in: testing lied)) (check: tests/acceptance/test_A_1_3.py)
- Invariant: On Cloud Run the store is durable (a GCS bucket); with no durable store configured, cloud mode refuses to start (why: A JSON-lines file in /tmp loses lines and fixes on every restart (Fergus gem 1)) (check: tests/acceptance/test_A_5_1.py)
- Invariant: Calls are counted at Mubit: every line stores the x-middleware-request-id of each call it made, and the counts in GET /stats come from those ids (why: Count effects at the external system, never in the agent's own report) (check: tests/acceptance/test_A_7_1.py)
- Tag: stopping_rule: build in rank order 1..n; stop when time runs out
- Tag: conflict_rule: real data and merged code win over prose
- Tag: trust_boundary: StatsBomb and Cricsheet downloads are untrusted data
- Tag: state_impact: only the store writes lines and fixes (data/lines.jsonl, JSON lines)
- Tag: freeze: builders never edit spec/ or tests/acceptance/; after code freeze only a rehearsed revert merges
- Tag: decisions: docs/stack.md rows are Decided or Proposed; a new dependency needs a reviewed stack change
- Tag: config_as_code: every Mubit-facing setting (prompt, tools, model, metadata) lives in agent/ files, never only in the console
- Tag: pre_existing: only our own tooling is copied from hackathon-starter (Dockerfile, scripts/deploy.sh, bootstrap), declared in the README; all app code is written at the event, with the starter read as a reference only

## Requirements
### R-1 [P0 · Traffic] Real, varied matches of both sports train the Mubit task tonight
rank 1 · state proposed · needs nothing · touches `data/`, `agent/`, `scripts/replay_matches.py`
Why: Mubit trains only after 25 kept examples, and its training day resets at 00:00 UTC; this is the Use-of-Mubit criterion
- A-1.1@1 Scenario: the StatsBomb and Cricsheet loaders turn a real match into Moments; a run of passes or dot balls yields no moment, a shot, goal, card, wicket, four or six does (`tests/acceptance/test_A_1_1.py`)
- A-1.2@1 Scenario: the system prompt, message template, tools.json and tool_choice sent for a football moment and a cricket moment are byte-identical; only the message's filled fields differ (`tests/acceptance/test_A_1_2.py`)
- A-1.3@1 Scenario: scripts/replay_matches.py --football N --cricket N picks distinct real matches, skips held-out and demo matches, opens one Mubit session per match, appends Lines to data/lines.jsonl and never replays a match already there (`tests/acceptance/test_A_1_3.py`)
- A-1.4@1 Scenario: with a later event planted in the feed, the model input for an earlier moment never contains it (`tests/acceptance/test_A_1_4.py`)
- A-1.5@1 Scenario: one live probe sends the exact production request (system prompt, tools, tool_choice, metadata) to Mubit and gets 200 with an x-middleware-request-id (live check, skipped offline) (`tests/acceptance/test_A_1_5.py`)

### R-2 [P0 · Spine] Server, store and live stream replay a match end to end
rank 2 · state proposed · needs R-1 · touches `core/`, `Makefile`, `data/sample/`
Why: Every other area builds on the replay stream and the store
- A-2.1@1 Scenario: GET /health returns 200 {status: ok} (`tests/acceptance/test_A_2_1.py`)
  - fixture: `{"method": "GET", "path": "/health"}` → `{"status": 200, "body": {"status": "ok"}}`
- A-2.2@1 Scenario: offline, POST /replays {match_id, speed} for each sample match, then GET /replays/{id}/stream sends moment, line and stats events in order, and every line is in the store (`tests/acceptance/test_A_2_2.py`)

### R-3 [P1 · Commentary] Lines are fast, right and in the sport's own terms
rank 3 · state proposed · needs R-1 · touches `agent/`
Why: A wrong or late line is worse than none; this is the demo
- A-3.1@1 Scenario: for a goal or a wicket, the trace shows get_score before the line, and the score in the line equals the store's score (`tests/acceptance/test_A_3_1.py`)
- A-3.2@1 Scenario: for an own goal, a saved penalty, a no-ball and a free hit from real feeds, each line contains that event's term (own goal, saved, no-ball, free hit) and names the player in the Moment, and never states a goal or a wicket that did not happen (`tests/acceptance/test_A_3_2.py`)
- A-3.3@1 Scenario: at 10x replay speed through Mubit, first word p50 <= 1.0 s and p95 <= 1.5 s (live check, skipped offline) (`tests/acceptance/test_A_3_3.py`)
- A-3.4@1 Scenario: switching from a football replay to a cricket replay, the next line is cricket commentary with cricket facts (`tests/acceptance/test_A_3_4.py`)
- A-3.5@1 Scenario: messy real matches (extra time, a penalty shootout, a super over, a rain-reduced chase, a no-result) replay without a crash, with lines only for real moments and the right score (`tests/acceptance/test_A_3_5.py`)
- A-3.6@1 Scenario: for a goal, a saved penalty, a six or a wicket, the line sounds like a live broadcast commentator at that moment (excited and emotional, at most 20 words), while every name and score in it is still right; a dull read-out of facts fails (`tests/acceptance/test_A_3_6.py`)

### R-4 [P1 · Fix loop] A producer's fix becomes training signal
rank 4 · state proposed · needs R-2 · touches `core/`, `agent/`
Why: A correction becoming a model update is the judges' Mubit criterion
- A-4.1@1 Scenario: POST /lines/{line_id}/fix {corrected_text, reason} stores the fix beside the original, sends it through the same Mubit task and session, records reply_matched, and the stream marks the line fixed (`tests/acceptance/test_A_4_1.py`)

### R-5 [P1 · Deploy] The spine runs on Cloud Run
rank 5 · state proposed · needs R-2 · touches `Dockerfile`, `scripts/deploy.sh`
Why: A product judges can open; deploy rehearsed Saturday morning, not discovered Sunday
- A-5.1@1 Scenario: make deploy from main prints a URL whose GET /health returns 200, and a sample replay against that URL streams moments and lines (live smoke on the real URL) (`tests/acceptance/test_A_5_1.py`)

### R-6 Match video, subtitles and an emotional voice, in both sports
rank 6 · state proposed · needs R-2 · touches `web/`
Why: What the judges see and hear
- A-6.1@2 Scenario: the live page plays the match's official highlights (embedded YouTube player, muted) and, as each mapped key moment plays, shows its line as a large subtitle and speaks it; a moment's line is never shown before that moment plays in the video (`tests/acceptance/test_A_6_1.py`)
- A-6.2@1 Scenario: one tap switches sport mid-demo, and the score bar, field and commentary follow (`tests/acceptance/test_A_6_2.py`)
- A-6.3@1 Scenario: the voice is a setting on the page; by default cricket is called in an Indian commentator voice and football in a British one, and changing the voice changes the next line's audio without reloading (`tests/acceptance/test_A_6_3.py`)
- A-6.4@2 Scenario: each demo match has a video map (YouTube id plus the video time of the first showing of each key moment) checked into data/; the server sends each mapped moment's line ahead of time tagged with its video time, and the page shows and speaks it when the YouTube player's current time reaches that video time (within 0.5 s); when the video buffers, pauses or is sought, the commentary waits for the player and never runs ahead of the picture (`tests/acceptance/test_A_6_4.py`)

### R-7 [P2 · Proof] The proof panel shows quality, cost and latency
rank 7 · state proposed · needs R-2, R-4 · touches `web/`, `core/`
Why: The track asks for quality, cost and latency side by side
- A-7.1@1 Scenario: GET /stats and the proof panel show p50/p95 latency, cost per line, line count, fix count and the adapter's result, matching the store (`tests/acceptance/test_A_7_1.py`)

### R-8 [P2 · Eval] Our trained model agrees with the big one
rank 8 · state proposed · needs R-1 · touches `eval/`
Why: Technical execution: evidence the adapter matches, not a claim
- A-8.1@1 Scenario: eval/agreement.py on held-out matches reports adapter-vs-provider agreement, counting empty, skipped or late lines as disagreements, or says 'not tested' with the reason; seeded with one known-bad line it reports a disagreement (`tests/acceptance/test_A_8_1.py`)

### R-9 [P3 · Submission] README, demo script and recording
rank 9 · state proposed · needs R-5 · touches `README.md`, `docs/demo.md`
Why: The submission and the demo criterion
- A-9.1@1 Scenario: README.md has what it is, how to run it, the live URL, a screenshot and data credits (StatsBomb, Cricsheet), with no placeholders (`tests/acceptance/test_A_9_1.py`)
- A-9.2@1 Scenario: docs/demo.md tells one human promise (every match gets a commentator) with the live call as its peak, at most one line on the tech, rehearsed once on the deployed URL (`tests/acceptance/test_A_9_2.py`)

## References
_(none)_

## Open questions
- Can the app call the trained adapter by API, or only Mubit's Try models console? (Mubit office hours)
- How do producer corrections and Good/Bad ratings feed Mubit training? (Mubit office hours)

## Waiting room
- A third sport, once real event data is found
- A hosted voice model if browser speech sounds flat

