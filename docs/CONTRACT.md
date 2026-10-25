# Contract

Written by the lead from the day's spec. Every area
builds against it; only the lead changes it (anything else is a change-request, AGENTS.md §6).

## Assignment

"Build a product that routes its LLM calls through Mubit and turns your corrections into model
updates for a recurring task." Track: Own your intelligence layer.

Demo: Kobe Bryant's 81 against Toronto (2006) replays and Touchline calls it aloud, the first word of text in
about 0.5 s (median), the producer fixes one wrong line, the big model's recorded lines are shown
where our trained commentator's will go (7 adapters on Mubit's console, none has passed its test yet, best
58.3%, and the app does not call an adapter), then one tap switches to India v Pakistan 2022 and the same commentator calls cricket.

## Shared core

| Piece | Where | Use it for |
|---|---|---|
| App factory | `core/app.py`, `create_app(store=None, deps=None)` | every route |
| Store | `core/store.py`: `all(kind)`, `append(kind, record)`; kinds `lines`, `fixes`, `auto_fixes`, `adapter`, `answers`, `voice`, `replays` | all state |
| Replayer | `core/replay.py`: `run_replay` publishes `moment`, `line`, `stats` | the live stream |
| Stats | `core/stats.py`: `stats(store)` | proof panel numbers, from the store only |
| Seam to #13 | `data.matches.list_matches()`, `data.matches.load_moments(match_id)`, `agent.commentator.commentate(moment, history)` | wired by `core.app.default_deps()` |
| Video map | `data.matches.video_map(match_id)` over `data/video/<sport>-<match_id>.json` | a demo match's YouTube video (A-6.4) |

Store: JSON-lines files under `STORE_DIR` (default `data/`). `MODE=cloud` keeps them as GCS objects
and refuses to start without `STORE_URL=gs://bucket/prefix`.

## Shapes

- **Moment** (data/): `{sport: "football"|"cricket"|"basketball"|"f1", match_id, idx, period, clock,
  type, team, players: {role: name}, outcome, score: {home, away} | {runs, wickets, target?} |
  {lap, laps, top: [{pos, driver, gap}]}, x?, y?, detail: {}}`. `clock` is `"mm:ss"` for football,
  `"over.ball"` for cricket, `"mm:ss"` left in the quarter for basketball and `"mm:ss"` since the
  start for f1; `period` is the half, the innings, the quarter (5+ is overtime) or the lap; f1's
  `top` is the top five, `gap` to the leader (`"leader"`, `"1.5 seconds"`, or `""` when timing lags);
  a car that has pitted before the feed gives its new place comes last with `pos: null,
  gap: "in the pit lane"`; an f1 moment's clock is the latest feed time it reads (A-1.4): a pass
  once it has held 20 s, a stop at pit exit, the flag 20 s after it;
  roles e.g. `shooter`, `keeper` / `batter`, `bowler`, `fielder` / `shooter`, `assist`, `stealer`,
  `lost_by` / `driver`, `passed`, `leader`, `winner`; `detail` holds sport fields (runs, extras,
  wicket kind, xG, card, play, player_points, lead_change, tyres, pit_lane_time); `x, y` on StatsBomb's 120 x 80 when known.
- **Line** (agent/): `{line_id, sport, match_id, moment_idx, text, model, latency_ms,
  first_word_ms, tokens_in, tokens_out, mubit_request_ids: [], tool_calls: [], created_at}`; tokens
  and latency summed over the whole tool loop; each id from `x-middleware-request-id`. A Line a
  replay stores carries its `replay_id` (#174; none before). `served_by` (#250): the `model` of
  Mubit's last reply, kept apart from what was asked (`model`): whatever model Mubit's reply
  names, as it names it; none before #250 or offline, and null on a line
  built from the data (`fallback: true`), whose text no model served. The provider reply also
  keeps every `x-middleware-*` response header (`middleware`); the line stores only `served_by`.
- **Cost records** (core/, #174): `voice` `{line_id, replay_id, model, chars}` for each ElevenLabs call
  that returned audio (`chars`: the text sent, tag included), and `replays` `{replay_id, match_id,
  line_ids}` for each replay played from its first moment to its last (not a jump, not the deploy's
  smoke, not abandoned or off air). `line_ids`: every line it said, cached ones too, so its model cost
  is what describing the match costs; a record without them (before this) is not counted.
- **Speakers, insights and replies** (core/insight.py, #130): every streamed and stored Line has
  `speaker: "lead" | "analyst"`. Moment lines are `"lead"`. With a video map, the quiet stretch after
  each mapped moment is filled with lines due at the last line's words / 2.7 + 2 s, until 6 s before
  the next mapped moment. Each one is a Line with `video_t`, said over a synthetic Moment
  `{...that moment, type: "Stat", outcome: "<kind>: <detail>", players: {}, detail: {speaker,
  "you are": <name>, partner: "<name>, the <role>", "call partner by name": "yes" | "no",
  "<name> just said": <last line>}}` with the same `idx` (names from `NAMES` in core/voice.py: Jim
  the lead, Julian the analyst; the name before "just said" is whoever said the last line) (a reply's outcome is "the lead answers the
  analyst, who just said: <last line>"). Its request is a line's message with the analyst's own
  system prompt (agent/analyst.md), no tools, never recorded, on `ANALYST_MODEL` (default
  claude-sonnet-5-5 with `thinking: {"type": "between_tools"}`, priced in core/stats.py; a
  model outside its prices is left out of the cost). An **insight** (`speaker: "analyst"`) carries `insight: {match_id, after_idx, n, kind, detail, heard, by, named}` (plus `never open with`
  when its first try opened like an earlier analyst line: no opener's first 3 words repeat in a replay), where `kind` is
  `"player profile"`, `"next to score"`, `"tally"`, `"score story"`, `"momentum"` or `"positions"`
  and `detail` is one short fact (a profile, odds or positions give one fact per insight; a
  pre-match fact names its period, such as "this season before tonight"), built only from moments up to `after_idx` and the pre-match pack. Every
  4th line in a stretch is a **reply** (`speaker: "lead"`, `reply: {..., kind: "reply"}`, no stat).
  A replay from the start opens with a **cold open** (#221) before the first mapped moment, from
  `video_start`: the lead's welcome naming the match, then the analyst's light line (`open: {...,
  kind: "cold open", n: 0 | 1, kickoff}`), each kept only if it ends 2 s before the first call and
  the open's speech stays within 15 s; said over the last moment before the first mapped one, else (`kickoff`) over the
  first with its counts zeroed and no history.
  All three are cached per (match_id, after_idx, n, v: 4) and reused by later replays; a replay
  makes at most 160 new calls for them. A fix on any goes back, unrecorded, with that line's own
  Stat request.
- **Fix** (core/): `{line_id, corrected_text, reason, match_id, moment_idx, said, wrong,
  created_at, mubit_request_id, correction, reply_passed: bool, recorded: bool}`; `reason` is at
  most 200 characters; `match_id`, `moment_idx`, `said` (the line, or its failed try) and `wrong`
  (the check's reasons) are the fixed line's, stamped so later requests need not read `lines` (a Fix
  stored before has none); `correction` is the exact user turn Mubit was given (#245);
  `reply_passed` is whether the provider's corrected reply passed the number check (a Fix before
  #245 has `reply_matched` instead); `recorded` is true only when Mubit recorded the correction
  for training (the owner's key). A Fix stored before it has none and counts as not recorded.
- **Match** (data/): `{match_id, sport, title?, sample: bool, youtube_id?, video_start?, embed?, peak_idx?,
  peak_video_start?}`; `sample`
  marks `data/sample/`; `youtube_id` and `video_start` are there when the match has a video map.
  `embed: false` (absent otherwise) means the video's owner blocks embedding: pages show its poster and
  a link to it on YouTube, never the player, and the commentary runs on the replay's own clock.
  `video_start` is the whole second the page starts the video at, 12 s before its first mapped moment (or 0): room for the two cold open lines (#221, #297).
  `peak_idx` (#163) is the moment "Jump to the big moment" starts at; `peak_video_start` is the video's start
  for that jump, 10 s before the first mapped moment from `peak_idx` on.
- **Video map** (data/video/): `{youtube_id, embed?, source, moments: [{idx, video_t}]}`; `idx` is a Moment's
  `idx`, `video_t` the seconds into the video of that moment's first showing, increasing with `idx`.
  Only moments matched with confidence are listed.

## HTTP

Errors: 404 not found, 409 busy or too early, 422 bad input, 503 commentator not configured.

- `GET /health` → `{status: "ok", mubit: "ok"|"degraded", mubit_reason}` (core, #401): `degraded`
  when `MUBIT_API_KEY` is unset (`mubit_reason: "MUBIT_API_KEY unset"`, also warned at startup) or the
  last Mubit call in this process failed (its status and error type, e.g. `"503 engine_unavailable"`,
  or the exception type when Mubit never answered) until a call succeeds; `mubit_reason` is null when
  `ok`. Read from the last call, never probed. `GET /stats` carries the same two fields, and the
  review page then shows "Mubit unavailable: lines use the fallback".
- `GET /matches` → `[Match]` (core over data/)
- `GET /matches/{id}/start?at=<idx>` → `{video_start}` (core, #188): the second the video starts at for
  a replay with `start_idx: idx`, as `peak_video_start` is for the peak; null without a video.
- `GET /teams/{sport}/{match_id}` → `{teams: [{team, form, squad}], head_to_head}` (core, #375): both
  sides' recent games (`{date, opponent, home, score, result}`), the squad's headline numbers
  (`{name, matches, headline}`) and the head-to-head, all before the match's date, from the graph.
  A section the graph can't give is `[]`; cached 60 s; 404 for an unknown match.
- `POST /replays {match_id, speed>0, start_idx?, smoke?}` → `{replay_id}` (core); `smoke: true` (the
  deploy's live smoke) is never counted as a full replay; `start_idx` (#163) starts the stream at
  that moment: earlier moments are never called. They are sent first, untimed (no `video_t`), so the score
  and clock are already there, each followed by the last line stored for it with `history: true`
  (shown, never spoken), then that line's latest `fixed` if it has one. 422 if no such moment.
  The budget guard (#244, core/guard.py): 429 with `Retry-After` past `REPLAYS_PER_HOUR` starts
  from one client (the first `X-Forwarded-For` hop) in an hour. With `MAX_LIVE_REPLAYS` replays
  already making lines, or today's spend past `DAILY_BUDGET_USD` (default 50), the replay plays each moment's
  stored line again as it was stored (its own `line_id`, `cached: true`), with no model or voice call, nothing
  stored and never counted as a full replay; 429 `{detail}` if the match has no stored lines. A 429's
  `detail` is viewer-safe: the page shows it.
- `GET /replays/{id}/stream` → SSE: per moment `moment`, `line`, `stats` in that order; a failed
  call skips only its line with `moment_off_air` `{code: "moment_off_air", idx}` (the page may
  ignore it); `error` `{code: "commentator_off_air", detail}` after 3 failures in a row, where `detail` is a fixed
  viewer-safe string ("Commentator is off air for a moment"), never the provider's error text (that
  goes to the server log); `end` last. A late subscriber gets the whole replay. (core)
  For a match with a video map, only mapped moments are called, the `moment` and `line` events carry
  `video_t` (seconds), and they are sent as soon as each line is ready rather than paced by `speed`:
  the page shows and speaks each line when the player reaches `video_t`.
  `linecheck` (#298): after a replay's checked lead moment line is out (not a fallback or a fix
  said again), Line check (agent/linecheck.py, the seeded request exactly) gives it a second
  opinion off its path, and the stored row is published. A cached replay's stored line is checked
  only if it has no row yet, so once ever (#297):
  `{line_id, match_id, moment_idx, labels, wrong, model, tokens_in, tokens_out, mubit_request_id,
  created_at}`. `labels` is `{score, leader, player_total, event}`, each `ok`, `wrong` or
  `not_said`, or null when the reply wasn't one canonical line; `wrong` lists the fields called
  wrong. It comes some time after its line, always before `end`. No call over the daily
  cap; recorded as `MUBIT_RECORD` says, never for a held-out match. A line is never unsaid.
- `POST /replays/{id}/seen` → 204 (core, #156): the page's heartbeat every 20 s once the stream has
  ended, playing or paused; 404 once forgotten. A finished replay is forgotten after FORGET_S (60 s)
  with no stream open and no request naming it (stream, seen, ask, players, shots, profile, fix).
- `GET /lines/{line_id}` → the stored Line, 404 if none (core): the live smoke checks each line it
  streamed was stored. A fixed line also carries `fix`: its latest Fix, with the correction call's
  `mubit_request_id` (#239); an unfixed line has no `fix` key. A line whose fix was sent to Line
  check as an example also carries `linecheck_example`: its latest `linecheck_fixes` row
  `{line_id, kind, gold, mubit_request_id, created_at}` (#305). `kind` is matched (Line check's
  reply already agreed with code), corrected (it disagreed and the correction turn followed),
  uncorrected or leader_only (a disagreement sent without a correction turn) or error (the call
  failed: no example). `mubit_request_id` is the last call's: the correction turn's when there is
  one. It says only that a training example was sent, never that a model was updated. Every line
  carries `scorecheck_examples`: the `scorecheck_examples` rows its fixes sent, source `fix`
  (`{id, match_id, idx, text, kind, gold, mubit_request_id, line_id, source, created_at}`, oldest
  first; `[]` until one is sent, #392, #400). `text` is the line as said or the fixed text; `gold`
  its score label from the event data; `fix_uid` the Fix that sent it (rows since #400). It also
  carries `scorecheck_receipts`: one `{fix_uid, line_id, sent, failed, held_out, created_at}` per Fix
  whose Score check send has ended, `sent` the examples it wrote (0 when each was already sent, can't
  be labelled or the match is held out), `failed` true when a call failed, and `held_out` true when
  the line's match is in `HELD_OUT` (eval/linecheck.py: never sent, so the eval stays fair; receipts
  before #506 have no `held_out`). No receipt yet: the send is still going, or Score check is off. Every Fix carries `fix_uid`, a fresh hex id (#400).
- `POST /lines/{line_id}/fix {corrected_text, reason?}` → Fix (core). With env `PRODUCER_TOKEN` set,
  it needs header `X-Producer-Token` equal to it (constant-time compare), else 401 and nothing is
  stored or sent to Mubit; unset (local, tests) the check is off (#232). `scripts/deploy.sh` sets it
  on Cloud Run from the deploy's own environment, so every deploy keeps it; a deploy without it
  leaves the check off (#255). It is a plain Cloud Run env var, not a secret: it is visible in the service config, in the deployer's gcloud logs and under `bash -x`. It stores the Fix in `fixes`
  beside the line, sends the correction turn (Agent below) and publishes `fixed` (the Fix), then
  `stats`, on the replay stream that carried the line; a late subscriber gets them too. 404 unknown
  line, 422 blank `corrected_text` (trimmed) or over 200 characters, 422 `{detail: {wrong: [...]}}`
  when the number check finds the fix contradicts the line's moment (the review queue's check, a
  milestone left out allowed; nothing stored or sent to Mubit) (#232), 503 no commentator or the
  Mubit call failed (nothing stored, so the page can send it again). A fix with reason Wrong score,
  Wrong player or Wrong fact also sends one Line check example after it is answered (#298, see
  `/stats` → `linecheck`). Every later replay of that
  moment says the newest fix's text, rechecked against the moment, instead of calling the model: a
  Line with `fixed: true` and `fix_id` (the fixed line's id), stored in `lines` (#232).
- `GET /converse/{sport}/{match_id}/token?replay_id=&moment_idx=` → `{signed_url, ctx}` (core, #380):
  a short-lived ElevenLabs signed URL for the browser and the conversation's context id (the replay
  and the moment, cut like Ask's). 503 when `CONVERSE_AGENT_ID`, `CONVERSE_LLM_SECRET` or
  `ELEVENLABS_API_KEY` is unset or the day is off air; 404 for a replay of another match or sport;
  409 before the first moment. The API key is never returned.
- `POST /converse/v1/chat/completions` (core, #380): the agent's custom LLM, OpenAI-compatible, SSE
  when `stream` is true. Bearer `CONVERSE_LLM_SECRET`; the context id (`ctx=...`) arrives in the system
  prompt. The last user turn is answered by the Ask path (`insight.checked_answer`).
- `POST /replays/{id}/ask {question, moment_idx?}` → Answer `{line_id, moment_idx, question, text,
  ...}` (core): a viewer's question (1-200 characters, trimmed) answered in 1-2 sentences from the
  match up to `moment_idx`, the last moment on the viewer's screen (default: the latest sent), never
  past the last moment the replay has sent, so the answer cannot spoil what is still to come. Stored
  in `answers` and spoken by `GET /lines/{line_id}/audio`, like a line; published as `answer` on the
  replay stream. Off air (the commentator call failed) it answers 200 with `{off_air: true, text:
  "Commentator is off air for a moment"}`, stores nothing and is still published. Past
  `DAILY_BUDGET_USD` the same, with `text` and `notice` "Commentator is off air for today". 404 unknown
  replay, 409 a question already in flight on this replay or no moment sent yet, 422 bad question,
  429 with `Retry-After` past `ASKS_PER_HOUR` from one client in an hour.
- `GET /replays/{id}/players/{name}/shots?moment_idx=` → `{player, sport, season: [{x, y, made,
  zone}], tonight: [{x, y, made, idx}], zones: [{zone, attempts, made, rate}]}` (core, #120): the
  player's pre-match shots from `data/packs/` plus tonight's up to `moment_idx` (default: the latest
  sent), never past the last moment the replay has sent. Basketball x, y are NBA LOC_X/LOC_Y (tenths
  of a foot, hoop at the origin), football StatsBomb 120x80. No LLM. 404 unknown replay, no pack for
  the match (cricket, F1) or unknown player; 409 no moment sent yet.
- `GET /replays/{id}/players?moment_idx=` → `[{name, team, record, named}]` (core, #140): everyone
  in the match, the pack's roster plus anyone the moments up to `moment_idx` name (`named: true`,
  the latest first); `record` false and `team` null for a name the pack lacks. Works before the
  first moment. 404 unknown replay or no pack for the match.
- `GET /replays/{id}/players/{name}/profile?moment_idx=` → `{player, team, sport, window: {from,
  to}, before, tonight, n, small_sample, text}` (core, #140): the pre-match record and tonight up
  to `moment_idx`, cut like `/shots`. `before` (null with no record) and `tonight` hold games,
  attempts, made and `zones: [{zone, attempts, made}]` (football adds `xg`); for cricket
  `batting: {powerplay|middle|death: {balls, runs, outs}}` and `bowling`; for F1 `before` holds
  wins, finishes, avg_finish, avg_gained and `tonight` `laps: [{lap, pos}]` while in the top five.
  `n` is the pre-match sample (attempts, balls or races), `small_sample` when n < 10, `text` the
  commentator's `get_player_profile`. Names resolve like the tool (accents, initials). No LLM.
  Optional `library: [{match_id, title, date, team, teammates: [name]}]` (#300), from the player
  graph, only when non-empty: the player's other bundled matches, oldest first, never this one, and
  who played on their side in each. Absent when the graph is off. 404 unknown replay, pack or
  player; 409 no moment sent yet.
- `GET /stage` → the backup live page (`core/stage.html`, static HTML over the routes here) (core)
- `GET /voices` → `[{id, label, default_for: "cricket"|"football"|"basketball"|"f1"|null, lang: "en-IN"|"en-GB"|"en-US"}]`, the page's voice
  setting: an Indian English commentator for cricket, a British one for football, an American
  play-by-play voice (Sam) for basketball, a British announcer for f1; `lang` is
  the BCP 47 tag the browser-speech fallback uses. `VOICE_<SPORT>` picks a sport's default: an id
  here, or a raw ElevenLabs voice id, listed as `<sport>-pick` (docs/voice.md). A pick that is the same
  ElevenLabs voice as an earlier entry carries `same_as: <that entry's id>`, so the page lists the voice once.
  The voice that reads a sport's analyst lines (`analyst_voice`) carries `analyst_for: [sports]`, so the page names the analyst. (core)
- `GET /lines/{line_id}/audio[?voice=<id>]` → `audio/mpeg` of the stored line (or answer) read by ElevenLabs
  in the chosen voice, or by default the voice for the line's sport. `eleven_v3` with an audio tag
  for the moment's kind (in the TTS text only, never the stored line); one retry, then
  `eleven_flash_v2_5` without the tag; `VOICE_MODEL_<SPORT>` overrides the model. The audio is
  made when the replay stores the line and cached, due before the video reaches its moment.
  404 for an unknown line or voice; 503 with no `ELEVENLABS_API_KEY`, every attempt failed,
  today's spend past `DAILY_BUDGET_USD` or a line a cached replay (#244) is saying with no audio
  saved (saved audio is played again), and the page then uses browser speech. The key never reaches the browser; each call logs
  `voice line=<id> first_byte_ms=<n> model=<model>`. (core)
- `GET /review` → `[{line_id, match_id, match, sport, moment_idx, clock, period, score, play, text,
  wrong, later_check, lines, others}]`, newest first: the producer's fix queue, one entry per
  mistake among the stored lead lines the number check flags, unfixed (`wrong` is the check's
  reasons). A line the number check passes but Line check flagged (#298) is queued too, its
  `wrong` `["Checker model: <field> may be wrong", ...]` (field `player_total` said `player total`). Grouping and `later_check` are under `GET /stats` → `autonomy` below. (core,
  `core/review.py`)
- `GET /stats` → `{lines, fixes, mubit_requests, first_word_ms_p50, first_word_ms_p95,
  latency_ms_p50, latency_ms_p95, tokens_in, tokens_out, cost_per_line_usd, by_speaker,
  fixes_recorded, fixes_toward_next, voice_chars, matches_measured, cost_per_match_usd,
  model_cost_per_match_usd, voice_cost_per_match_usd, fixes_auto_sent, spoken_from_fix, autonomy,
  autonomy_by_match, linecheck, scorecheck, earlier_tasks, budget, mubit, mubit_reason}` (core;
  `mubit` and `mubit_reason` as `GET /health`'s, GET /stats only). The `stats` SSE event carries the same object, without `budget`.
  - `budget: {daily_budget_usd, spent_today_usd, off_air}` (#244): the cap (null when off), the
    model and voice spend of lines, answers and Line checks created today (UTC), and whether it
    is past the cap.
  - `voice: {provider: "elevenlabs"|"browser", last_error, since, characters_left}` (#306, GET /stats only): who
    speaks the lines. `browser` from ElevenLabs' last failure until it returns audio again, with
    `last_error` its `detail.status` on a 401 or 429 (e.g. `quota_exceeded`), `timeout`,
    `network`, or the status, and `since` when the failing began (ISO, UTC). No key:
    `not_configured`. Kept per process. The page then shows "Voice: browser fallback (ElevenLabs
    unavailable)" on air and on the Proof card. `characters_left: int|null`: the main key's
    ElevenLabs `character_limit` minus `character_count` (`GET /v1/user/subscription`), read at
    most every 5 minutes; null with no key or when it can't be read. `scripts/demo_check.py`
    fails its voice row below 30,000. Once the main key answers `quota_exceeded`, each call tries
    the keys in `ELEVENLABS_API_KEY_FALLBACKS` (comma-separated) in order; a backup key's 402 is
    tried once more in George, the one voice a free-plan key may speak. Unset, nothing changes.
  - `linecheck: {checked, flags, rules_missed, fixes_sent, examples_today,
    examples_today_by_kind, heldout}` (#298, #305, #317): live lead lines Line check
    checked (`linechecks` rows), those it flagged a field `wrong` on, the flags on lines the rules
    check passed (every live check is on such a line, so today it equals `flags`), and producer
    fixes sent to Line check as examples (`linecheck_fixes` rows: a fix with reason Wrong score,
    Wrong player or Wrong fact whose line code can label, sent on the owner's key; kind error
    left out). `examples_today` counts those created today (UTC) and `examples_today_by_kind`
    splits them by kind, e.g. `{"corrected": 2, "matched": 1}`. `heldout` (#317) is
    `eval/linecheck_heldout.json` as `eval/linecheck_eval.py --json` wrote it from one keyed,
    unrecorded run on the held-out labels: `{labels, lines, wrong, rules: {caught, false_alarms},
    line_check: {caught, false_alarms}, errors}`, or `null` without the file, when the card shows
    neither the result nor the note below. The Proof card's Checker model row says it in counts, e.g. "held-out: caught 3 of 5 wrong lines (rules: 1 of 5),
    3 false alarms", never as a percentage. A flag only sends a line to the fix queue; it never
    unsays it.
  - `scorecheck: {examples_sent, by_source: {answer_key, auto_fixed, human}, from_fixes_by_kind,
    held_out: {[what]: {agree, scored, unparsed, recorded_at}}, next_training, recorded}` (#321,
    #363): Score check (agent/scorecheck.py), the one task trained on Mubit, which /stats leads
    with. `examples_sent` counts the examples sent to Mubit (`scorecheck_examples` rows) and
    `by_source` splits them by the row's `source`: `seed` (the match data's answer key, by
    `eval/seed_scorecheck.py --go`) is `answer_key`, `auto` (the number check's own retry) is
    `auto_fixed`, `fix` (a producer's fix, the same reasons as Line check, once per line) is
    `human`, each 0 when absent. `held_out` is each model's latest score on the frozen held-out
    lines (`scorecheck_evals`, written by `--score FILE --record WHAT`). `next_training` is a fixed
    "after 01:00 UK", when Mubit's daily training limit resets. `recorded` is Score check's
    latest `adapter` record, in the shape of an `earlier_tasks.adapters` entry below, or `null`
    until `python -m eval.record_adapter --task score_check` records a version from the console.
  - `earlier_tasks: {adapter, adapters}` (#363): the commentary tasks trained before Score check,
    kept under one key so they never read as the headline. The Proof card folds them into one
    collapsed "Earlier tasks" line.
  - `by_speaker: {lead, analyst}`, each `{model, served_by, lines, first_word_ms_p50,
    first_word_ms_p95, cost_per_line_usd}`: the lead's calls and the analyst's stat lines apart (a
    line with no `speaker` is the lead's). `served_by` (#250): the lines' `served_by` values,
    comma-separated, and `served_lines` the count of lines that carry one (lines from before #250
    and lines built from the data carry none). The Proof card says "Served by ..." alone only when
    `served_lines` equals `lines`; otherwise it shows `model` and "served by ... on N lines". The
    lead's also has `audio_first_ms_p50`, `audio_first_ms_p95` and
    `audio_lines` (#233): ms from its moment's publish (in a video replay, the video reaching the
    moment, if later; audio ready before then is 0) to its audio ready on the server, over the
    `audio_lines` lead lines voiced when the replay stored them; both percentiles are null when
    `audio_lines` is 0.
  - `fixes_recorded: int`: fixes with `recorded: true`; `fixes` counts every stored fix.
  - `fixes_auto_sent: int`: the `auto_fixes` records, corrections the number check sent to Mubit
    itself (reason `auto: number check`): a lead line's rejected first try, corrected to its accepted
    retry (#162).
    Stored apart from `fixes`, so never in `fixes`, `fixes_recorded` or the review queue's fixed lines.
    Not the Proof card's Auto-fixed, which is `autonomy.auto_fixed`: that counts calls, and only those
    stored after #204 flagged a kept retry `retried`, so it leaves out the earlier auto fixes this
    counts. A correction that failed to send has no record, so it is in `autonomy.auto_fixed` only.
  - `spoken_from_fix: int`: stored lead lines a replay said in a producer's fixed words (`fixed:
    true`, #232). Never a model call, so never in `autonomy`.
  - `autonomy: {called, first_time, auto_fixed, to_human}` (#204): the lead's moment calls the
    number check saw (stored `checked: true`; not the analyst's lines, the lead's replies to them, or
    any line stored before the flag) by how the check left them: passed first
    time; `auto_fixed`, the retry passed (stored `retried: true`); `to_human`, the retry failed too, so the fallback was
    said and the line is stored `fallback: true` with the failed try as `tried` and the check's
    reasons as `wrong`, which the review queue lists. The four always sum: `called` is the rest's
    total. `autonomy_by_match: {match_id: the same}`. `GET /review` also lists stored lead lines
    that today's check fails but that passed it (or predate it) when said: those entries carry
    `later_check: true` (a `to_human` try, `false`) and are never counted here (#220).
    `GET /review` gives one entry per mistake (#227): the lines whose check gives the same
    `wrong` at the same match and moment are one entry, the newest line's, with `lines` (how many
    distinct wordings) and `others` (the older wordings, newest first). A fix on any of them
    clears every line of that mistake stored up to the fix (`created_at`); one said after it is a new entry.
  - `fixes_toward_next: int`: recorded fixes since the latest `adapter` record (all of them before one),
    leaving out any whose corrected reply failed the number check (`reply_passed: false`, #245).
  - `voice_chars: int`: characters in every `voice` record.
  - `cost_per_match_usd: number | null`: the mean full replay's spend, `model_cost_per_match_usd`
    (the tokens of every line it said, cached or not, and of its answers × list price) plus `voice_cost_per_match_usd` (its `voice`
    characters × ElevenLabs' price per model); over `matches_measured` full replays. A part is null
    with no full replay, a model with no known price, or (voice) no `voice` record; the total then too.
  - `cost_per_line_usd: number | null`: mean cost of the stored lines, tokens × the model's list
    price; null when no line's model has a known price.
  - `earlier_tasks.adapter: {state: "collecting"|"testing"|"passed", summary, kept: int|null, agree: int|null,
    total: int|null, cost_measurable: bool, console}`. `state` is what the record shows:
    `passed` only when Mubit's gate was recorded as passed, `testing` once a version, score or failed
    gate is recorded, else `collecting`; never inferred from the record's `status` or a count of fixes. `summary`
    says it in words, as of the record's time, e.g. "Testing: no version passed; best 55.8% of a 95%
    target, as of 24 Oct 2026 13:04 UTC." Nothing enforces a number of fixes before a version, so
    none is reported. The record's own `status` (the console's word, e.g. "training") is not
    reported: beside `state` it read as a contradiction. `kept`, `agree` and `total`
    come from the latest `adapter` record in the store, which `python -m eval.record_adapter` appends
    from Mubit's console; before one exists, `collecting` and nulls. `kept` is never inferred from
    stored lines, since a stored line doesn't prove Mubit kept it. `cost_measurable` is false while
    the app can't call the adapter. These are the commentary task's: a record with no `task` is
    commentary's, and another task's record leaves this key and `fixes_toward_next` alone.
    `console` (#317) is `data/mubit_console.json`, Mubit's console overview read by hand at
    `read_at`: `{source, read_at, how, tasks, adapters, serving, target, listed: {[name]: {status,
    examples, quality}}}` (keyed by name: the `stats` event carries no brackets), or `null` without the file. It is a dated reading, never live data, and
    changes only when someone reads the console again and commits it. The Proof card's Earlier tasks
    line shows it as "Mubit console, 24 Oct 19:15 UTC: 8 tasks, 7 adapters, 0 serving; best 58.3% of a
    95% target".
  - `earlier_tasks.adapters: {[task]: {state, version: int|null, version_id: str|null, score: number|null,
    target: number|null, passed: bool|null, kept: int|null, recorded_at, source: str|null,
    versions: [{version, version_id, score, target, passed, recorded_at, source}]}}`: each Mubit
    task's latest `adapter` record (#209), keyed `commentary`, `where_are_we` or `line_check` (Score
    check's is `scorecheck.recorded`); a task with no record is absent. `versions` (#321) is every version the task's
    records name, oldest first, each as its latest record says it.
    `score` is the console's "matched N% of the provider model's answers", `target` its target (e.g.
    95) and `passed` its gate, null unless a version is recorded (the recorder refuses a verdict
    without `--version` and `--version-id`); `kept` is the console's kept examples, never requests. Each field is only what
    `python -m eval.record_adapter --task ...` recorded from the console; null where it didn't say.

## Agent

- Producer fixes as context: each line's request (`build_request(header, past, fixes)`) appends to
  the user message the match's last 5 stored fixes said at or before its moment (when, the line
  said or the failed try, the check's reasons or the producer's reason, the producer's line; each
  quoted). Never the system prompt, tools or model; with none, the request is byte-identical. The
  replay reads them (`match_fixes(store, match_id)`, only `fixes`; an unstamped Fix's line is read
  from `lines` once) on every call, so a fix applies to the next lines straight away. `correct()` builds its request without them.
- System prompt `agent/prompt.md`, never templated. User message from one frozen template
  `agent/message.md` carrying the sport, the moment, its score and recent play.
- Tools `agent/tools.json`, sport-neutral: `get_score`, `get_player`, `get_recent_play`;
  `tool_choice: auto`; at most one tool round per line. Output: plain text, at most 20 words. Line
  requests carry exactly these three: Mubit fingerprints the tools, so another would split the task.
- Every model call goes through Mubit (`https://api.mubit.ai/anthropic`), model `claude-haiku-4-5`;
  one session per match in `metadata.user_id = "match-<sport>-<id>"`; no browser calls to Mubit.
  `FakeProvider` offline.
- Correction (`agent.commentator.correct`): the line's original request (same prompt, tools, model
  and `metadata.user_id`, so the same Mubit task and session) plus the line as the assistant turn
  and a correction turn (#245): "Producer correction: <reason>", the facts at the moment (score,
  leader, player total), "The producer's line: <text>" and "Say your line again, corrected". Only
  the messages differ from the line's request. The provider writes the fixed line. The request goes
  unrecorded first (`x-middleware-record: off`); only when that reply passes the number check is
  the same request sent again on the owner's key, recorded. `reply_passed` is the recorded reply's
  check (false, with nothing recorded, when the first reply failed). An auto-fix gives the
  checker's own reasons. Mubit
  has no feedback API, so this turn is the training signal.
- The commentator sees only moments up to the current one; a later event never reaches the model.
- Answer (`agent.commentator.answer`): the request for the moment on screen with the system prompt
  `agent/ask.md`, the last five lines said and the viewer's question (whitespace collapsed, quoted as a JSON
  string, so it cannot forge a field) appended to the user message;
  same model and session; at most 30 words. Sent with `x-middleware-record: off`: its own
  system prompt would otherwise split the one Mubit task the lines train.
- Ask-only tools (`agent/ask_tools.json`, appended to the line tools for answers only), answered by
  `core/predict.py` from the match's pre-match pack (`data/packs/`) and the moments up to the one on
  screen, never a later one: `get_player_profile(name)` (pre-match totals and zone rates, or cricket
  batting by phase and bowling, each with tonight's counts and a Beta-binomial blend; "small sample"
  when n < 10) and `get_next_score_odds()` (per team, among players seen so far and not substituted
  off: share of attempts times make rate, or xG per shot in football; sums to 1 per team). A match
  with no pack answers "No pre-match record for this event."

## Check

`make check` (ruff, ruff format, pytest) and `make smoke` (check, then an offline replay of each
sample match through the app with `FakeProvider`). Contract tests:
`tests/test_core_spine.py`.
