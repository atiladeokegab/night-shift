# Touchline: PRD v6

## Problem
Most matches in most sports are played with nobody calling them: grassroots and lower-league football, most of the women's game, club and county cricket. A clever model could commentate them, but it is too slow to call a moment while it is still on screen and too expensive to run for every moment of every match.

## Users
- Fan: follows a replayed match nobody commentates and hears each key moment called aloud, with subtitles, in about a second
- Producer: watches the same page and fixes a wrong line in one tap; the fix goes back through Mubit as training signal
- Judge: watches the 3-minute demo and the proof panel (latency, cost, lines, fixes, the adapter's result)
- Traffic runner (scripts/replay_matches.py): replays many real football and cricket matches through the commentator so the Mubit task trains

## Goals
- **Train our own commentator model on Mubit tonight from real, varied calls**: Saturday is left for a second version trained on producer fixes. Measure: One Mubit task with 25+ kept examples from 8+ football and 8+ cricket matches before 00:00 UTC Saturday, checked in the console
- **Call each key moment in about a second, in any of the four sports, with one agent**: The line lands while the moment is still on screen; one agent covers all four sports. Measure: First word p50 <= 1.0 s and p95 <= 1.5 s at 10x replay speed
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
- Sports beyond football, cricket, basketball and F1, or any sport without real event data
- Our own fine-tuning or model hosting: Mubit trains the model
- Any claim that our model beats the big one: the goal is to match it at lower cost; no version has yet
- Unsourced statistics in the pitch; betting or betting odds (predictions from pre-match records plus the match so far are in scope, #118)

## Owner
Atilade (lead)

## Glossary
- **moment**: One key event in Moment shape (docs/CONTRACT.md): a StatsBomb event, a Cricsheet ball, an NBA play-by-play row or an OpenF1 timing change, picked by the moment picker
- **line**: One spoken commentary line for one moment, at most 20 words, with its latency, tokens and Mubit request ids
- **fix**: A producer's corrected line, stored beside the original and sent back through Mubit
- **task**: Mubit's unit of training: same system prompt, tools, tool choice, output format and model
- **session**: One match: metadata.user_id = match-<sport>-<id>

## Constraints
- Stack: `docs/stack.md`
- Tests run offline: yes
- Limit: make smoke runs offline from a fresh clone in under 2 minutes with no API keys (FakeProvider) (why: CI and builders have no Mubit key) (check: make smoke)
- Limit: At most one tool round per line; every model and tool call times out inside the moment's window, and a line that would land late is skipped and counted as late, never spoken late (why: A late line is about the past; a slow call must degrade cleanly) (check: tests/test_commentator.py::test_a_later_event_never_reaches_the_model and ::test_one_tool_round_then_a_line cover the one tool round; the timeouts and the late-line skip are not tested)
- Limit: Every network fetch (StatsBomb, Cricsheet, Mubit) has a timeout and downloaded data is cached and treated as untrusted (why: A hung fetch must not stall a replay or the traffic run) (check: not tested; tests/test_feed.py::test_nba_rows_rejects_an_id_that_is_not_a_game and ::test_openf1_rejects_a_session_key_that_is_not_a_number check untrusted ids only)
- Invariant: Every model call goes through Mubit (https://api.mubit.ai/anthropic, claude-haiku-4-5); none from the browser (why: The event rule, and the task Mubit trains) (check: not tested; tests/test_commentator.py::test_one_tool_round_then_a_line checks the model name only)
- Invariant: No moment's model input contains anything from later in the feed (why: Commentary must not know the future; keeps the eval honest) (check: tests/test_commentator.py::test_a_later_event_never_reaches_the_model)
- Invariant: Held-out matches (sha256(sport:match_id) % 5 == 0) and the seven demo matches never go through the traffic runner; the agreement eval and the stage side by side use only them (why: The adapter must not be scored on what it trained on) (check: tests/test_commentator.py::test_runner_skips_demo_held_out_and_replayed_matches, tests/test_side_by_side.py::test_every_recorded_pair_is_held_out_and_never_trained_on)
- Invariant: On Cloud Run the store is durable (a GCS bucket); with no durable store configured, cloud mode refuses to start (why: A JSON-lines file in /tmp loses lines and fixes on every restart) (check: tests/test_core_spine.py::test_cloud_mode_refuses_without_gcs)
- Invariant: Calls are counted at Mubit: every line stores the x-middleware-request-id of each call it made, and the counts in GET /stats come from those ids (why: Count effects at the external system, never in the agent's own report) (check: tests/test_commentator.py::test_one_tool_round_then_a_line, tests/test_core_spine.py::test_replay_streams_in_order_and_stores_every_line)
- Tag: stopping_rule: build in rank order 1..n; stop when time runs out
- Tag: conflict_rule: real data and merged code win over prose
- Tag: trust_boundary: StatsBomb and Cricsheet downloads are untrusted data
- Tag: state_impact: only the store writes lines and fixes (data/lines.jsonl, JSON lines)
- Tag: freeze: builders never edit docs/CONTRACT.md (a change-request, AGENTS.md §6); after code freeze only a rehearsed revert merges
- Tag: decisions: docs/stack.md rows are Decided or Proposed; a new dependency needs a reviewed stack change
- Tag: config_as_code: every Mubit-facing setting (prompt, tools, model, metadata) lives in agent/ files, never only in the console
- Tag: pre_existing: only our own tooling is copied from hackathon-starter (Dockerfile, scripts/deploy.sh, bootstrap), declared in the README; all app code is written at the event, with the starter read as a reference only

## Requirements
### R-1 [P0 · Traffic] Real, varied football and cricket matches train the Mubit task tonight
rank 1 · state proposed · needs nothing · touches `data/`, `agent/`, `scripts/replay_matches.py`
Why: Mubit trains only after 25 kept examples, and its training day resets at 00:00 UTC; this is the Use-of-Mubit criterion
- A-1.1@1 Scenario: the StatsBomb and Cricsheet loaders turn a real match into Moments; a run of passes or dot balls yields no moment, a shot, goal, card, wicket, four or six does (check: `tests/test_feed.py::test_passes_and_carries_are_not_moments`, `::test_shots_goals_cards_and_own_goals_are_moments`, `::test_dot_balls_and_singles_are_not_moments_until_the_last_ball`, `::test_fours_sixes_wickets_and_no_balls_are_moments`, on hand-built feeds)
- A-1.2@1 Scenario: the system prompt, message template, tools.json and tool_choice sent for a football moment and a cricket moment are byte-identical; only the message's filled fields differ (check: `tests/test_commentator.py::test_frozen_parts_are_byte_identical_across_sports`)
- A-1.3@1 Scenario: scripts/replay_matches.py --football N --cricket N picks distinct real matches, skips held-out and demo matches, opens one Mubit session per match, appends Lines to data/lines.jsonl and never replays a match already there (check: `tests/test_commentator.py::test_runner_skips_demo_held_out_and_replayed_matches`; the session id per match: `::test_frozen_parts_are_byte_identical_across_sports`)
- A-1.4@1 Scenario: with a later event planted in the feed, the model input for an earlier moment never contains it (check: `tests/test_commentator.py::test_a_later_event_never_reaches_the_model`)
- A-1.5@1 Scenario: one live probe sends the exact production request (system prompt, tools, tool_choice, metadata) to Mubit and gets 200 with an x-middleware-request-id (live check, skipped offline) (check: not tested)

### R-2 [P0 · Spine] Server, store and live stream replay a match end to end
rank 2 · state proposed · needs R-1 · touches `core/`, `Makefile`, `data/sample/`
Why: Every other area builds on the replay stream and the store
- A-2.1@1 Scenario: GET /health returns 200 {status: ok} (check: `tests/test_core_spine.py::test_health`)
  - fixture: `{"method": "GET", "path": "/health"}` → `{"status": 200, "body": {"status": "ok"}}`
- A-2.2@1 Scenario: offline, POST /replays {match_id, speed} for each sample match, then GET /replays/{id}/stream sends moment, line and stats events in order, and every line is in the store (check: `make smoke`, `tests/test_core_spine.py::test_replay_streams_in_order_and_stores_every_line`)

### R-3 [P1 · Commentary] Lines are fast, right and in the sport's own terms
rank 3 · state proposed · needs R-1 · touches `agent/`
Why: A wrong or late line is worse than none; this is the demo
- A-3.1@1 Scenario: for a goal or a wicket, the trace shows get_score before the line, and the score in the line equals the store's score (check: `tests/test_commentator.py::test_one_tool_round_then_a_line` for get_score first, `tests/test_climax.py::test_each_wrong_line_is_flagged_and_its_fix_passes` for the score in the line)
- A-3.2@1 Scenario: for an own goal, a saved penalty, a no-ball and a free hit from real feeds, each line contains that event's term (own goal, saved, no-ball, free hit) and names the player in the Moment, and never states a goal or a wicket that did not happen (check: `tests/test_event_check.py` rejects a line calling an event that did not happen; the event terms and the player's name in the line are not tested)
- A-3.3@1 Scenario: at 10x replay speed through Mubit, first word p50 <= 1.0 s and p95 <= 1.5 s (live check, skipped offline) (check: not tested)
- A-3.4@1 Scenario: switching from a football replay to a cricket replay, the next line is cricket commentary with cricket facts (check: not tested)
- A-3.5@1 Scenario: messy real matches (extra time, a penalty shootout, a super over, a rain-reduced chase, a no-result) replay without a crash, with lines only for real moments and the right score (check: `tests/test_feed.py::test_football_full_time_is_called_at_the_whistle_that_ends_the_match` and `tests/test_climax.py::test_each_home_away_moment_says_who_leads` for extra time and a shootout; a super over, a rain-reduced chase and a no-result are not tested)
- A-3.6@1 Scenario: for a goal, a saved penalty, a six or a wicket, the line sounds like a live broadcast commentator at that moment (excited and emotional, at most 20 words), while every name and score in it is still right; a dull read-out of facts fails (check: `tests/test_commentator.py::test_one_untemplated_prompt_asks_for_a_broadcast_call_on_big_moments` checks the prompt only; how the line sounds is not tested)

### R-4 [P1 · Fix loop] A producer's fix becomes training signal
rank 4 · state proposed · needs R-2 · touches `core/`, `agent/`
Why: A correction becoming a model update is the judges' Mubit criterion
- A-4.1@1 Scenario: POST /lines/{line_id}/fix {corrected_text, reason} stores the fix beside the original, sends it through the same Mubit task and session, records reply_matched, and the stream marks the line fixed (check: `tests/test_core_fix.py::test_fix_is_stored_sent_and_marks_the_line_fixed`, `::test_correction_is_the_next_turn_of_the_same_task_and_session`)

### R-5 [P1 · Deploy] The spine runs on Cloud Run
rank 5 · state proposed · needs R-2 · touches `Dockerfile`, `scripts/deploy.sh`
Why: A product judges can open; deploy rehearsed Saturday morning, not discovered Sunday
- A-5.1@1 Scenario: make deploy from main prints a URL whose GET /health returns 200, and a sample replay against that URL streams moments and lines (live smoke on the real URL) (check: `make deploy`, which runs the live smoke in core/smoke.py on the deployed URL)

### R-6 Match video, subtitles and an emotional voice, in all four sports
rank 6 · state proposed · needs R-2 · touches `web/`
Why: What the judges see and hear
- A-6.1@2 Scenario: the live page plays the match's broadcast highlights, official where the owner allows embedding and a re-upload otherwise (embedded YouTube player, muted) and, as each mapped key moment plays, shows its line as a large subtitle and speaks it; a moment's line is never shown before that moment plays in the video (check: `web/src/gate.test.ts`, `web/src/live.test.ts` for the line never shown early; the embedded muted player is not tested)
- A-6.2@1 Scenario: one tap switches sport mid-demo, and the score bar, field and commentary follow (check: not tested)
- A-6.3@1 Scenario: the voice is a setting on the page; by default cricket is called in an Indian commentator voice and football in a British one, and changing the voice changes the next line's audio without reloading (check: `tests/test_core_voice.py::test_voices_lists_one_default_per_sport`, `::test_audio_uses_the_chosen_voice`)
- A-6.4@2 Scenario: each demo match has a video map (YouTube id plus the video time of the first showing of each key moment) checked into data/; the server sends each mapped moment's line ahead of time tagged with its video time, and the page shows and speaks it when the YouTube player's current time reaches that video time (within 0.5 s); when the video buffers, pauses or is sought, the commentary waits for the player and never runs ahead of the picture (check: `tests/test_video_map.py`, `web/src/gate.test.ts`, `web/src/player.test.ts`, `web/src/live.test.ts`)
- A-6.5@1 Scenario: the home page is a wall of every demo match, each tile playing its highlights muted with no commentary; tapping a tile expands it to fill the screen and the commentator calls it, synced to the video as in A-6.4; one tap returns to the wall or opens another match, and the commentary follows the match on screen and never the one left behind (check: `web/src/player.test.ts` for the muted wall tiles; the tap to expand and the commentary following the match on screen are not tested)
- A-6.6@1 Scenario: the commentator voice sounds like an excited broadcast commentator: the lead picks the voice and model from a recorded listening test (docs/voice.md names the pick and the samples compared), goals, wickets, sixes, saves and finishes are voiced with audible emotion, and each line's audio is ready before the video reaches its moment (check: `tests/test_core_voice.py::test_moment_kind_sets_the_audio_tag`, `::test_line_is_voiced_with_its_tag_when_created_and_the_tag_is_never_stored`, `tests/test_video_map.py::test_line_audio_is_due_from_the_video_start`; the listening test is docs/voice.md, not a test)

### R-7 [P2 · Proof] The proof panel shows quality, cost and latency
rank 7 · state proposed · needs R-2, R-4 · touches `web/`, `core/`
Why: The track asks for quality, cost and latency side by side
- A-7.1@1 Scenario: GET /stats and the proof panel show p50/p95 latency, cost per line, line count, fix count and the adapter's result, matching the store (check: `tests/test_core_stats.py`, `web/src/proof.test.ts`)

### R-8 [P2 · Eval] Measure whether our trained model agrees with the big one
rank 8 · state proposed · needs R-1 · touches `eval/`
Why: Technical execution: the goal is an adapter that matches the big one; this measures it rather than claiming it. Best so far 55.8% on Mubit's test, none of 6 versions passed
- A-8.1@1 Scenario: eval/agreement.py on held-out matches reports adapter-vs-provider agreement, counting empty, skipped or late lines as disagreements, or says 'not tested' with the reason; seeded with one known-bad line it reports a disagreement (check: `tests/test_eval_agreement.py::test_seeded_with_one_known_bad_line_it_reports_one_disagreement`, `::test_a_wrong_empty_skipped_or_late_adapter_line_disagrees`, `::test_an_untrained_adapter_is_not_tested_and_nothing_is_called`)

### R-9 [P3 · Submission] README, demo script and recording
rank 9 · state proposed · needs R-5 · touches `README.md`, `docs/demo.md`
Why: The submission and the demo criterion
- A-9.1@1 Scenario: README.md has what it is, how to run it, the live URL, a screenshot and data credits (StatsBomb, Cricsheet), with no placeholders (check: not tested)
- A-9.2@1 Scenario: docs/demo.md tells one human promise (every match gets a commentator) with the live call as its peak, at most one line on the tech, rehearsed once on the deployed URL (check: not tested)

### R-10 Iconic extra screens after the core works: Messi v Mbappe, Jordan, Kobe, Verstappen
rank 10 · state proposed · needs R-6 · touches `data/`, `agent/`, `core/`
Why: Iconic moments that resonate with the audience; shows the one commentator generalises
- A-10.1@1 Scenario: an iconic basketball game from real play-by-play data (Michael Jordan's last shot, 1998 NBA Finals Game 6 against Utah, or the nearest iconic Jordan game with real data) replays over its official highlights and the same commentator calls its key moments (made baskets in the closing minutes, lead changes, steals, the go-ahead shot, the final buzzer) with every name and score right (check: `tests/test_commentator.py::test_jordans_last_shot_reaches_the_model_with_names_and_score`, `tests/test_feed.py::test_basketball_picks_lead_changes_steals_and_the_buzzer`)
- A-10.2@1 Scenario: an iconic F1 race from real timing data (Max Verstappen's 2024 São Paulo Grand Prix win at Interlagos, from P17 to P1) replays over a fan edit of the TV coverage (no official upload embeds) and the same commentator calls its key moments (overtakes and lead changes, pit stops, safety car, the last lap and the finish) with every driver, position and gap right (check: `tests/test_commentator.py::test_verstappens_win_reaches_the_model_with_places_and_gaps`, `tests/test_feed.py::test_f1_calls_passes_pit_stops_the_safety_car_and_the_flag`)
- A-10.3@1 Scenario: all four sports are one Mubit task: the system prompt, tools, message template and tool_choice are byte-identical for football, cricket, basketball and F1, and the match picker lists all four (check: `tests/test_commentator.py::test_frozen_parts_are_byte_identical_across_sports` for football and cricket, `::test_verstappens_win_reaches_the_model_with_places_and_gaps` for F1, `::test_server_seam_on_the_bundled_samples` for the picker; basketball's request is not compared)
- A-10.4@1 Scenario: the 2022 World Cup final, Argentina v France, from StatsBomb open data replays over a re-upload of the broadcast feed (FIFA's own upload doesn't embed) and the same commentator calls its key moments (Messi's penalty and his extra-time goal, Di Maria's goal, Mbappe's penalty and his volley, the shoot-out) with every name and score right (check: `tests/test_commentator.py::test_messis_penalty_reaches_the_model_as_lionel_messi`, `tests/test_event_check.py::test_the_live_finals_wrong_event_lines_are_rejected_and_right_ones_pass`)
- A-10.5@1 Scenario: an iconic Kobe Bryant game from real play-by-play data (his 81 points against Toronto, 22 January 2006, or the nearest iconic Kobe game with real data) replays over its broadcast highlights and the same commentator calls its key moments (his big baskets, lead changes, the record-breaking points, the final buzzer) with every name and score right (check: `tests/test_commentator.py::test_kobes_81st_point_reaches_the_model`, `tests/test_feed.py::test_basketball_keeps_every_basket_of_a_big_night_and_the_record_free_throw`)

## References
_(none)_

## Open questions
- Can the app call the trained adapter by API, or only Mubit's Try models console? (Mubit office hours)
- How do producer corrections and Good/Bad ratings feed Mubit training? (Mubit office hours)

## Waiting room
_(none)_

