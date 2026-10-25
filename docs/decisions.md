# Touchline: the design decisions and why we made them

Each record says what we decided, the problem it answered, the reasoning with its evidence, what we
rejected, what it costs us, and where it lives in the code. Figures come from
[evidence.md](evidence.md), a test or a merged PR (`gh pr view N`). Anything we could not evidence
is marked **not measured**.

| # | Decision | In one line |
|---|---|---|
| [1](#1-audio-description-for-blind-and-low-vision-fans) | Audio description for blind and low-vision fans | The fan with the biggest gap, not "commentary for everyone" |
| [2](#2-replay-real-event-data-never-invent-it) | Replay real event data | Facts come from the feed, never the model's memory |
| [3](#3-check-the-numbers-in-code-retry-once-then-speak-a-line-built-from-the-data) | Check numbers in code, retry once, then a data-built line | A wrong score is never said on the first try's word |
| [4](#4-checks-with-answer-keys-from-code-line-check-and-score-check) | Line check and Score check: answer keys from code | A recurring task whose right answer the data settles |
| [5](#5-every-model-call-through-mubit-record-only-what-the-check-clears) | Every model call through Mubit; record only what clears the check | Training data we would stand behind |
| [6](#6-a-producers-fix-is-the-next-turn-of-the-lines-own-call) | A fix is the next turn of the line's own call | Mubit has no feedback API, so a fix is a recorded example |
| [7](#7-held-out-matches-never-train) | Held-out matches never train | Nothing is scored on what it learned from |
| [8](#8-stored-lines-and-saved-clips-fresh-lines-only-with-a-producer-token) | Stored lines and saved clips; fresh lines need a producer token | A fan's replay makes no model call |
| [9](#9-claude-haiku-by-default-sonnet-where-haiku-slipped-lead_model-to-override) | Haiku by default, Sonnet where Haiku slipped | Fastest first word for lines; accuracy for stats and checks |
| [10](#10-elevenlabs-eleven_v3-with-audio-tags-two-fallbacks) | ElevenLabs `eleven_v3`, two fallbacks | An excited voice, and never silence |
| [11](#11-one-agent-one-frozen-prompt-four-sports) | One agent, one frozen prompt, four sports | The sport goes in the message |
| [12](#12-frozen-prompts-pinned-by-tests-and-a-code-freeze-gate) | Frozen prompts and a freeze gate | Each prompt change forked a Mubit task |
| [13](#13-surrealdb-embedded-in-the-process-not-a-server) | SurrealDB embedded, not a server | A graph with no new service or secret |
| [14](#14-json-lines-in-gcs-as-the-store) | JSON lines in GCS as the store | Durable on Cloud Run, no database to run |
| [15](#15-cloud-run-one-warm-instance-at-most-one) | Cloud Run, one warm instance, at most one | No cold start on stage; in-memory state stays correct |
| [16](#16-a-daily-budget-guard) | A daily budget guard | A public URL cannot run up the bill |
| [17](#17-accessibility-first-ui) | Accessibility-first UI | Eyes closed, live regions only when silent, keyboard |
| [18](#18-a-deterministic-offline-smoke-test-as-the-merge-gate) | Deterministic offline smoke as the merge gate | CI has no keys, so the gate needs none |

---

## 1. Audio description for blind and low-vision fans

**Decision.** Touchline is an audio describer: it calls each key moment aloud for fans who can't
see the screen, for matches nobody describes.

**Context.** The first framing (PRD v6) was commentary for any match nobody calls. That is a nice
to have for a sighted fan, who can watch. For a fan who can't see the screen, a match with no
describer is a match they can't follow.

**Why.** The gap is large and documented (evidence.md, The problem): Sky Sports describes about
109 of the Premier League's 380 games a season; a 2015 survey found 4 of 20 Premier League clubs
with trained audio describers; US rules exempt live programming; at Wrexham the fans and local
sponsors raised £4,000 to fund it themselves. At least 2.2 billion people have a vision
impairment (WHO). Touchline's cost is about $0.45 a replay, voice included, over 84 replays
(`eval/live_stats_2026-10-24.json`). Repositioned in #206 to #208.

**Alternatives rejected.** General commentary for sighted fans: weaker need, and it hides the
reason every number must be right (a blind listener has no screen to check against).
Video-based description: the feed is event data, and vision input is a non-goal (PRD v6).

**Consequences.** The UI must work with eyes closed (decision 17), a wrong number is worse than
silence (decision 3), and the fallback line must be speakable (#200). Whether blind fans prefer it
to the crowd and a ticker: **not measured** (no user study).

**Where.** `core/fallback.py:186` (lines written for a listener), `web/src/eyes.ts:2`.

## 2. Replay real event data, never invent it

**Decision.** Every match is a replay of a real event feed: StatsBomb (football), Cricsheet
(cricket), NBA play-by-play (basketball) and OpenF1 (F1). No synthetic matches.

**Context.** We need many varied matches for Mubit to learn from, and a commentator whose facts can
be checked.

**Why.** Mubit judges whether usage is real; padded or synthetic calls would be worthless training
data (PRD v6, "Real traffic only"). A real feed is also the answer key: the number check
(decision 3) can only compare a line with the truth if the truth exists. The graph holds 620 real
football matches (612 from StatsBomb, 8 NWSL results; `tests/test_readme_claims.py`).

**Alternatives rejected.** A live match feed: paid, and no live matches during the event window
(non-goal in PRD v6). Generated matches: unverifiable, and Mubit would see them as fake traffic.

**Consequences.** We are limited to sports and matches with open data. Downloads are untrusted
input and are validated (`tests/test_feed.py::test_nba_rows_rejects_an_id_that_is_not_a_game`).
No moment's request contains anything later in the feed
(`tests/test_commentator.py::test_a_later_event_never_reaches_the_model`).

**Where.** `agent/feed.py:32` (the demo matches), `scripts/replay_matches.py:61`.

## 3. Check the numbers in code, retry once, then speak a line built from the data

**Decision.** Before a lead line is spoken, code compares it with the moment's data: score, who
leads, the margin, players' counts and, in football, the kind of event. A line that fails is tried
once more; if the retry fails too, a line built only from the data is spoken.

**Context.** A model wrote "Chicago Bulls take the lead, 85-86!" when Utah led 86-85
(evidence.md, Anatomy of a fix). For a listener who can't see the score bar, that line is the
truth.

**Why.** The data already holds the answer, so code can decide it exactly, in microseconds, with no
second model to trust. One retry fixes most slips at the cost of one more call; the data-built line
guarantees nothing wrong reaches air when both tries fail (#182, #200). We report its limits
plainly: on 6 wrong lines in a held-out set it caught 2 (a 95% interval of about 10% to 70%); on
the set its rules were written against, 14 of 15 (evidence.md, How well the check works).

**Alternatives rejected.** Trusting the model: the Jordan line shows why. A second model as judge
in the hot path: slower, costs per line, and its own errors would need checking. Silence on a
failed line: a blind fan loses the moment entirely.

**Consequences.** It covers only what code can test; a line can still be wrong in ways it does not
look for (evidence.md lists four). Counting omissions too, precision on the held-out set falls to
18%, so some right lines are regenerated needlessly. Every failed try goes to the producer's fix
queue.

**Where.** `core/insight.py:1768` (`checked`), `core/insight.py:1429` (`wrong_numbers`),
`core/fallback.py:186`; tests `tests/test_checker_eval.py`, `tests/test_fallback.py:45`.

## 4. Checks with answer keys from code: Line check and Score check

**Decision.** Alongside commentary, two recorded Mubit tasks ask Claude to check a stored line
against its moment's facts and answer JSON (`ok`, `wrong`, `not_said`). The answer key comes from
code, never a model; a line code can't label is never sent.

**Context.** Commentary has no single right answer, so a trained commentator is hard to grade.
Each commentary task's best version reached 58.3% of Mubit's 95% target (evidence.md).

**Why.** A check has exact answers the data settles, so Mubit's test means something. Score check
was split off because Claude repeated its own Line check answer only 95% of the time on a 60-line
pilot: an adapter would have had to beat Claude's own consistency (#333). Line check runs on Sonnet
because Haiku agreed with the code's answer on 25% of a 40-line pilot, Sonnet on 90%
(`agent/linecheck.py:13`). Mubit's 'Check one line of 2' task (one of our two line-checking
tasks; the console cuts the name short) shows 94.6% for its first version, testing v1, in testing
(console read by hand, 25 Oct 06:27 UTC; `data/mubit_console.json`, #560). The app does not call an
adapter.

**Alternatives rejected.** Training only the commentator: no stable target. Labels from a model:
the answer key would inherit the errors it is meant to catch.

**Consequences.** Some examples are planted (a right line with one field made wrong, marked
`planted: true`) to balance the labels; they are not real commentator errors. A Line check flag
only sends a line to the fix queue; it never stops it being said.

**Where.** `agent/linecheck.py`, `agent/scorecheck.py`, `eval/linecheck.py`;
`tests/test_scorecheck.py:21` pins the task.

## 5. Every model call through Mubit; record only what the check clears

**Decision.** Every Claude call goes to Mubit's Anthropic endpoint. Lines are made unrecorded; a
lead line that clears the number check is sent again, off the viewer's path, on a recording key.
The live site's key records nothing (`MUBIT_RECORD=off`).

**Context.** Mubit trains on the calls it records. Recording the first call meant recording lines
the check later rejected (#399).

**Why.** Training data should be lines we would stand behind (#413). Separating the demo key from
the training key keeps judges' clicks from becoming training traffic; training comes from
`scripts/replay_matches.py` over distinct real matches. Each line stores the Mubit request id of
every call, and `GET /stats` counts calls from those ids (PRD v6 invariant). 2,161 examples were
sent to training, 60 from producer fixes (evidence.md, README figures).

**Alternatives rejected.** Calling Anthropic directly: nothing for Mubit to learn from, and it
breaks the event's rule. Recording everything: wrong lines become training data.

**Consequences.** A recorded reply is a new generation we can't see first, so it can still fail;
it is marked `recorded: true, reply_passed: false` and does not count toward the next version. The
second call costs extra. No version trained on our data is in use: the console (25 Oct, 00:14 UTC)
shows 11 tasks, 8 adapters and none in use.

**Where.** `agent/commentator.py:36` (endpoint), `:480` (`default_provider`), `:510`
(`unrecorded_provider`), `scripts/deploy.sh:104`.

## 6. A producer's fix is the next turn of the line's own call

**Decision.** A fix is sent as a follow-up turn of the wrong line's original request: the request,
the wrong line, then a turn with what was wrong, the facts and the producer's line. The model
writes the corrected line, and that reply is recorded. The match's last five fixes also go into
the user message of every later line in that match.

**Context.** Mubit has no feedback API (evidence.md, Why a correction is a follow-up turn).

**Why.** Same system prompt, tools and model means the same Mubit task, so a fix lands as a
training example for that task, not a new one. Asking the model to write the fix teaches a
correction, not "repeat this text" (#252). Carrying fixes in the user message makes them apply at
once: after the Terland fix, three of the six later lines on that match said "the Seagulls"
(`eval/fix_then_later_live_20261024.txt`, #501). A fix the data contradicts gets 422 and never
reaches Mubit (#240).

**Alternatives rejected.** Putting fixes in the system prompt: forks the task. Sending the
producer's text word for word as the answer (before #245): teaches copying.

**Consequences.** Only a fix whose corrected reply clears the number check is recorded; a fix to
an analyst's stat line is never recorded. What a version trained on fixes learns: **not
measured**, since no such version has been tested.

**Where.** `agent/commentator.py:403` (`correct`), `:377` (`correction_turn`), `:191`
(`build_request` takes `fixes`); `tests/test_core_fix.py`.

## 7. Held-out matches never train

**Decision.** A match is held out when `sha256(sport:match_id) % 5 == 0`. Held-out and the demo
matches are never sent through the training runner.

**Context.** An adapter scored on matches it trained on would look better than it is.

**Why.** A hash is stable, needs no list to maintain and can't be tuned by hand. 74 of 74 held-out
lines agree in Score check's held-out comparison (evidence.md, README figures).

**Alternatives rejected.** A hand-picked test list: easy to leak. A random split per run: changes
between runs.

**Consequences.** About a fifth of the real matches never feed training. Every line of the WSL
match (3913122) and the F1 race (9636) is held out of Line check too.

**Where.** `agent/feed.py:45`, `scripts/replay_matches.py:61`;
`tests/test_commentator.py::test_runner_skips_demo_held_out_and_replayed_matches`.

## 8. Stored lines and saved clips; fresh lines only with a producer token

**Decision.** A match already called in full replays its stored lines and saved ElevenLabs clips,
with no model or voice call. New lines are made only when none are stored, a fix is newer than the
lines, or a request with a valid producer token asks for `fresh`. `scripts/precompute.py` makes
and saves every match's lines and audio ahead of time.

**Context.** Judges and fans open the same seven matches. Making the lines again each time costs
money and a cold voice call, and gives a different line each time.

**Why.** A stored line already cleared the number check and its audio is ready before the video
reaches the moment (#539, #537). The producer token keeps paid generation behind one secret
(#240); a fix without it gets 401.

**Alternatives rejected.** Fresh lines on every replay: about $0.45 each, and a slow voice on a
cold start. Caching in the browser: per viewer, and the key would have to be public.

**Consequences.** A fan hears what the commentator said when the lines were made, not a new call.
Stored replays make no new Line check call (#446).

**Where.** `core/app.py:255` (cached or made), `core/guard.py:84` (`cached_commentator`),
`core/app.py:65` (producer token); `tests/test_cached_first.py:18`, `:65`.

## 9. Claude Haiku by default, Sonnet where Haiku slipped, `LEAD_MODEL` to override

**Decision.** Lead lines use `claude-haiku-4-5`; the analyst's stat lines, Line check and Score
check use `claude-sonnet-5-5`. `LEAD_MODEL` swaps the lead model per deploy without a code change.

**Context.** A line must land while the moment is still on screen (PRD v6: first word p50 at or
under 1.0 s).

**Why.** Haiku had the fastest measured first word (`docs/stack.md`); live, the lead's first word
is 547 ms at the median (saved `/stats`). Sonnet went where facts mattered more than speed: Haiku
slipped on the stat lines' facts in a probe (`agent/commentator.py:33`) and agreed with the code's
answer on 25% of a Line check pilot against Sonnet's 90%. `LEAD_MODEL` exists so stored lines can
be made with a bigger model when speed matters less (#536), since the precompute calls the
deployed service.

**Alternatives rejected.** Sonnet for every line: slower first word (Sonnet's first word for lead
lines: **not measured**). One model everywhere: Haiku's check answers were not good enough.

**Consequences.** Changing `LEAD_MODEL` changes the task fingerprint, so recorded lines from a
different model are a different Mubit task. Which model made the stored lines is in each line's
record, not fixed here.

**Where.** `agent/commentator.py:31`, `:199`, `:214`; `scripts/deploy.sh:141`;
`tests/test_commentator.py:82`.

## 10. ElevenLabs `eleven_v3` with audio tags, two fallbacks

**Decision.** Lines are spoken by ElevenLabs `eleven_v3` with an audio tag per moment kind
(`[shouting]` for a goal, `[hushed]` for a chase build-up). If v3 can't make it, `eleven_flash_v2_5`
without the tag; if that fails, browser speech.

**Context.** The voice is what a blind fan experiences; a flat read of "Goal" undersells the moment.

**Why.** A listening test on 2026-10-23 compared 10 voices; the picks were the British Football
Announcer for football and Raju, Cricket Match Commentator, for cricket (`docs/voice.md`). Only v3
reads tags; flash would say "[shouting]" aloud. v3 takes 2 to 3 s warm and 11 to 15 s cold, so
audio is started as soon as a line exists, ahead of the picture.

**Alternatives rejected.** Browser speech only: robotic, no emotion. Flash only: fast but flat.
Calling ElevenLabs from the browser: exposes the key.

**Consequences.** Paid per character; a characters-left meter is on `/stats` (#316). The tag is
sent only to ElevenLabs, never stored or recorded.

**Where.** `core/voice.py:27`, `:28`; `tests/test_core_voice.py`.

## 11. One agent, one frozen prompt, four sports

**Decision.** One commentator with one system prompt and one tool set calls football, cricket,
basketball and F1; the sport goes in the user message.

**Context.** Mubit trains per task, keyed on the system prompt, tools, output format and model.

**Why.** A prompt per sport would split the training data four ways. One prompt also shows the
agent generalising: the same request calls Messi's penalty, Jordan's last shot and Verstappen's
win (PRD v6, R-10).

**Alternatives rejected.** A prompt or persona per sport: four tasks, each with a quarter of the
data (non-goal in PRD v6).

**Consequences.** The prompt must stay general; sport terms come from the message and the tools.
Basketball's request is not compared byte for byte in a test.

**Where.** `agent/prompt.md`, `agent/tools.json`, `agent/commentator.py:191`;
`tests/test_commentator.py:92`.

## 12. Frozen prompts pinned by tests, and a code-freeze gate

**Decision.** The commentator, Line check and Score check prompts are frozen, and tests pin them. A
CI gate lets only PRs labelled `fix` merge after code freeze.

**Context.** Each prompt change started a new Mubit task: the console shows 11 tasks and 8
adapters, with our commentary split across them (evidence.md).

**Why.** That split is the cost we paid; freezing stops it recurring. Byte-identity tests fail a
PR that would fork a task by accident. The freeze gate keeps the demo build stable in the last
hours, enforced by CI, not memory.

**Alternatives rejected.** Tuning the prompt freely: every tweak resets training. A freeze by
agreement: easy to break under deadline.

**Consequences.** Better prompts wait for a new task. After freeze, only fixes ship.

**Where.** `tests/test_commentator.py:92`, `tests/test_scorecheck.py:21`,
`.github/workflows/freeze-gate.yml:12`.

## 13. SurrealDB embedded in the process, not a server

**Decision.** Players, teams, matches and seasons live in a graph in SurrealDB's embedded engine,
in memory, inside the app's process. If it fails, the app serves the JSON packs.

**Context.** Follow a player and the Teams panel need traversals (a player's other matches, a
team's form, head to head).

**Why.** Embedded means no new service, secret or setting on Cloud Run (#304). Loads use fixed ids
in file order, so every load is the same; the graph answers like the packs
(`tests/test_graph.py:43`). It holds 620 football matches.

**Alternatives rejected.** A SurrealDB or Postgres server: another thing to deploy, secure and pay
for. Joins over JSON files: slow and hand-written for each query.

**Consequences.** The graph loads at startup and costs memory; it loads on a thread so a cold start
answers sooner (#530). Startup time on Cloud Run: **not measured** here.

**Where.** `core/graph.py:3`, `:132`; `pyproject.toml:11`.

## 14. JSON lines in GCS as the store

**Decision.** Lines and fixes are JSON-lines files: local files in development, GCS
objects on Cloud Run. Cloud mode refuses to start without a bucket.

**Context.** A JSON-lines file in `/tmp` loses every line and fix on a Cloud Run restart.

**Why.** It is the simplest durable store that fits one process (IDEA.md ceiling). Each append is a
compare-and-swap on the object's generation, and text is cached with its generation so a read makes
no GCS call while unchanged (#323).

**Alternatives rejected.** Cloud SQL or Firestore: a database to run for one writer. Local disk:
lost on restart.

**Consequences.** Each append rewrites the object, which slows as files grow; the ceiling is a
database once two producers edit at once.

**Where.** `core/store.py:103`, `:193`; `tests/test_core_spine.py:151`.

## 15. Cloud Run, one warm instance, at most one

**Decision.** Deploy to Cloud Run with `--min-instances 1` and `--max-instances 1`.

**Context.** Judges open the URL cold. Rate limits and recent audio live in one process's memory.

**Why.** A warm instance avoids a cold start in front of judges (#536). One instance at most keeps
in-memory limits and audio correct without shared state. Cold start time: **not measured**.

**Alternatives rejected.** Scale to zero: cheapest, but a cold start on stage. Many instances:
needs a shared limiter and audio bucket (IDEA.md ceiling).

**Consequences.** A warm instance costs money while idle; the deploy script marks it a shortcut
until judging ends. One instance caps throughput; a load check runs five judges at once
(`make load`).

**Where.** `scripts/deploy.sh:21`, `:143`, `:144`.

## 16. A daily budget guard

**Decision.** At most 4 replays make new lines at once, 10 replay starts and 20 Asks per client an
hour, and a $50 daily spend cap; past a limit, stored lines play instead.

**Context.** A public URL with paid model and voice calls behind it.

**Why.** The guard turns overload into the cached path, not an error (#251). A stored replay never
counts against a client's hourly starts (#421). A failed spend read never takes the site off air
(#274).

**Alternatives rejected.** No limits: one loop could spend the budget. Hard 429s only: a fan gets
nothing when the stored lines would do.

**Consequences.** Over the cap, Ask says the commentator is off air for today. The limits are
per-process (decision 15).

**Where.** `core/guard.py:143`; `tests/test_guard.py`.

## 17. Accessibility-first UI

**Decision.** The page works with eyes closed: **E** covers the video while the line and score
carry on, the caption is a live region only while the voice is silent, state changes are announced,
and every action works from the keyboard.

**Context.** The users can't see the screen (decision 1).

**Why.** A screen reader reading the caption over the voice makes both unintelligible, so the
caption announces only when silent (#183). Each keyboard and screen-reader claim is traced to code
and a test (evidence.md, Keyboard and screen reader). No serious or critical axe finding at 390 and
1280 px (`web/e2e/a11y.spec.ts`).

**Alternatives rejected.** Accessibility as a later pass: retrofitted live regions talk over audio.

**Consequences.** No blind user has tested it: **not measured**.

**Where.** `web/src/eyes.ts:2`, `web/src/components/Caption.tsx:22`, `web/src/focus.ts:5`.

## 18. A deterministic offline smoke test as the merge gate

**Decision.** `make smoke` runs lint, the full test suite and a replay of each sample match with a
fake provider, with every API key blanked. CI runs it on every PR into `integration`.

**Context.** CI and builders have no Mubit or ElevenLabs key, and a flaky gate stalls a team.

**Why.** A fake provider gives the same lines every run, so a red smoke is a real regression
(PRD v6 limit: offline from a fresh clone in under 2 minutes). Live behaviour is checked separately
by the deploy's live smoke.

**Alternatives rejected.** Live calls in CI: needs secrets, costs money, flaky.

**Consequences.** The smoke can't catch a provider-side change; the live smoke after deploy covers
that.

**Where.** `Makefile:14`, `agent/commentator.py:879` (`FakeProvider`),
`.github/workflows/smoke.yml`.
