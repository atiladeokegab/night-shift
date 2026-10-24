# Contract

Written by the lead's agent from the day spec (`~/hub/projects/night-shift/day-spec.md`). Every area
builds against it; only the lead changes it (anything else is a change-request, AGENTS.md §6).

## Assignment

"Build a product that routes its LLM calls through Mubit and turns your corrections into model
updates for a recurring task." Track: Own your intelligence layer.

Demo: Kobe Bryant's 81 against Toronto (2006) replays and Night Shift calls it aloud, the first word of text in
about 0.5 s (median), the producer fixes one wrong line, the big model's recorded lines are shown
where our trained commentator's will go (6 versions trained, none has passed Mubit's test yet, best
55.8%, and the app does not call an adapter), then one tap switches to India v Pakistan 2022 and the same commentator calls cricket.

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
  replay stores carries its `replay_id` (#174; none before).
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
- **Fix** (core/): `{line_id, corrected_text, reason, created_at, mubit_request_id,
  reply_matched: bool, recorded: bool}`; `recorded` is true only when Mubit recorded the correction
  for training (the owner's key). A Fix stored before it has none and counts as not recorded.
- **Match** (data/): `{match_id, sport, title?, sample: bool, youtube_id?, video_start?, embed?, peak_idx?,
  peak_video_start?}`; `sample`
  marks `data/sample/`; `youtube_id` and `video_start` are there when the match has a video map.
  `embed: false` (absent otherwise) means the video's owner blocks embedding: pages show its poster and
  a link to it on YouTube, never the player, and the commentary runs on the replay's own clock.
  `video_start` is the whole second the page starts the video at, 25 s before its first mapped moment (or 0): room for the cold open (#221).
  `peak_idx` (#163) is the moment "Jump to the big moment" starts at; `peak_video_start` is the video's start
  for that jump, 10 s before the first mapped moment from `peak_idx` on.
- **Video map** (data/video/): `{youtube_id, embed?, source, moments: [{idx, video_t}]}`; `idx` is a Moment's
  `idx`, `video_t` the seconds into the video of that moment's first showing, increasing with `idx`.
  Only moments matched with confidence are listed.

## HTTP

Errors: 404 not found, 409 busy or too early, 422 bad input, 503 commentator not configured.

- `GET /health` → `{status: "ok"}` (core)
- `GET /matches` → `[Match]` (core over data/)
- `GET /matches/{id}/start?at=<idx>` → `{video_start}` (core, #188): the second the video starts at for
  a replay with `start_idx: idx`, as `peak_video_start` is for the peak; null without a video.
- `POST /replays {match_id, speed>0, start_idx?, smoke?}` → `{replay_id}` (core); `smoke: true` (the
  deploy's live smoke) is never counted as a full replay; `start_idx` (#163) starts the stream at
  that moment: earlier moments are never called. They are sent first, untimed (no `video_t`), so the score
  and clock are already there, each followed by the last line stored for it with `history: true`
  (shown, never spoken), then that line's latest `fixed` if it has one. 422 if no such moment.
  The budget guard (#244, core/guard.py): 429 with `Retry-After` past `REPLAYS_PER_HOUR` starts
  from one client (the first `X-Forwarded-For` hop) in an hour. With `MAX_LIVE_REPLAYS` replays
  already making lines, or today's spend past `DAILY_BUDGET_USD`, the replay plays each moment's
  stored line again as a new Line (`cached`: the stored line's id, no tokens), with no model or voice
  call and never counted as a full replay; 429 `{detail}` if the match has no stored lines. A 429's
  `detail` is viewer-safe: the page shows it.
- `GET /replays/{id}/stream` → SSE: per moment `moment`, `line`, `stats` in that order; `error`
  `{code: "commentator_off_air", detail}` if the commentator fails, where `detail` is a fixed
  viewer-safe string ("Commentator is off air for a moment"), never the provider's error text (that
  goes to the server log); `end` last. A late subscriber gets the whole replay. (core)
  For a match with a video map, only mapped moments are called, the `moment` and `line` events carry
  `video_t` (seconds), and they are sent as soon as each line is ready rather than paced by `speed`:
  the page shows and speaks each line when the player reaches `video_t`.
- `POST /replays/{id}/seen` → 204 (core, #156): the page's heartbeat every 20 s once the stream has
  ended, playing or paused; 404 once forgotten. A finished replay is forgotten after FORGET_S (60 s)
  with no stream open and no request naming it (stream, seen, ask, players, shots, profile, fix).
- `GET /lines/{line_id}` → the stored Line, 404 if none (core): the live smoke checks each line it
  streamed was stored. A fixed line also carries `fix`: its latest Fix, with the correction call's
  `mubit_request_id` (#239); an unfixed line has no `fix` key.
- `POST /lines/{line_id}/fix {corrected_text, reason?}` → Fix (core). With env `PRODUCER_TOKEN` set,
  it needs header `X-Producer-Token` equal to it (constant-time compare), else 401 and nothing is
  stored or sent to Mubit; unset (local, tests) the check is off (#232). It stores the Fix in `fixes`
  beside the line, sends the correction turn (Agent below) and publishes `fixed` (the Fix), then
  `stats`, on the replay stream that carried the line; a late subscriber gets them too. 404 unknown
  line, 422 blank `corrected_text` (trimmed) or over 200 characters, 422 `{detail: {wrong: [...]}}`
  when the number check finds the fix contradicts the line's moment (the review queue's check, a
  milestone left out allowed; nothing stored or sent to Mubit) (#232), 503 no commentator or the
  Mubit call failed (nothing stored, so the page can send it again). Every later replay of that
  moment says the newest fix's text, rechecked against the moment, instead of calling the model: a
  Line with `fixed: true` and `fix_id` (the fixed line's id), stored in `lines` (#232).
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
  404 unknown replay, pack or player; 409 no moment sent yet.
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
  404 for an unknown line or voice; 503 with no `ELEVENLABS_API_KEY`, every attempt failed or
  today's spend past `DAILY_BUDGET_USD`,
  and the page then uses browser speech. The key never reaches the browser; each call logs
  `voice line=<id> first_byte_ms=<n> model=<model>`. (core)
- `GET /stats` → `{lines, fixes, mubit_requests, first_word_ms_p50, first_word_ms_p95,
  latency_ms_p50, latency_ms_p95, tokens_in, tokens_out, cost_per_line_usd, adapter, by_speaker,
  fixes_recorded, fixes_toward_next, voice_chars, matches_measured, cost_per_match_usd,
  model_cost_per_match_usd, voice_cost_per_match_usd, fixes_auto, spoken_from_fix, autonomy,
  autonomy_by_match, budget}` (core). The `stats` SSE event carries the same object, without `budget`.
  - `budget: {daily_budget_usd, spent_today_usd, off_air}` (#244): the cap (null when off), the
    model and voice spend of lines and answers created today (UTC), and whether it is past the cap.
  - `by_speaker: {lead, analyst}`, each `{model, lines, first_word_ms_p50, first_word_ms_p95,
    cost_per_line_usd}`: the lead's calls and the analyst's stat lines apart (a line with no
    `speaker` is the lead's).
  - `fixes_recorded: int`: fixes with `recorded: true`; `fixes` counts every stored fix.
  - `fixes_auto: int`: the `auto_fixes` records, fixes the number check sent itself (reason
    `auto: number check`): a lead line's rejected first try, corrected to its accepted retry (#162).
    Stored apart from `fixes`, so never in `fixes`, `fixes_recorded` or the review queue's fixed lines.
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
  - `fixes_toward_next: int`: recorded fixes since the latest `adapter` record (all of them before one).
  - `voice_chars: int`: characters in every `voice` record.
  - `cost_per_match_usd: number | null`: the mean full replay's spend, `model_cost_per_match_usd`
    (the tokens of every line it said, cached or not, and of its answers × list price) plus `voice_cost_per_match_usd` (its `voice`
    characters × ElevenLabs' price per model); over `matches_measured` full replays. A part is null
    with no full replay, a model with no known price, or (voice) no `voice` record; the total then too.
  - `cost_per_line_usd: number | null`: mean cost of the stored lines, tokens × the model's list
    price; null when no line's model has a known price.
  - `adapter: {status: "not_trained"|"training"|"ready", kept: int|null, needed, agree: int|null,
    total: int|null, cost_measurable: bool}`: `needed` is 25. `status`, `kept`, `agree` and `total`
    come from the latest `adapter` record in the store, which `python -m eval.record_adapter` appends
    from Mubit's console; before one exists, `not_trained` and nulls. `kept` is never inferred from
    stored lines, since a stored line doesn't prove Mubit kept it. `cost_measurable` is false while
    the app can't call the adapter. These are the commentary task's: a record with no `task` is
    commentary's, and another task's record leaves this key and `fixes_toward_next` alone.
  - `adapters: {[task]: {status, version: int|null, score: number|null, target: number|null,
    passed: bool|null, kept: int|null, recorded_at}}`: each Mubit task's latest `adapter` record
    (#209), keyed `commentary`, `where_are_we` or `line_check`; a task with no record is absent.
    `score` is the console's "matched N% of the provider model's answers", `target` its target (e.g.
    95) and `passed` its gate; `kept` is the console's kept examples, never requests. Each field is only what
    `python -m eval.record_adapter --task ...` recorded from the console; null where it didn't say.

## Agent

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
  and "Producer correction. Reply with exactly this line: <text>"; `reply_matched` records whether
  the reply was exactly that line. Mubit has no feedback API, so this turn is the training signal.
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
sample match through the app with `FakeProvider`). Contract tests: `tests/acceptance/test_A_2_*.py`,
`tests/test_core_spine.py`.
