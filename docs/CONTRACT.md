# Contract

Written by the lead's agent from the day spec (`~/hub/projects/night-shift/day-spec.md`). Every area
builds against it; only the lead changes it (anything else is a change-request, AGENTS.md §6).

## Assignment

"Build a product that routes its LLM calls through Mubit and turns your corrections into model
updates for a recurring task." Track: Own your intelligence layer.

Demo: the 2023 Women's World Cup final replays and Night Shift calls it aloud in under a second, the
producer fixes one wrong line, our trained commentator calls a moment beside the big model, then one
tap switches to India v Pakistan 2022 and the same commentator calls cricket.

## Shared core

| Piece | Where | Use it for |
|---|---|---|
| App factory | `core/app.py`, `create_app(store=None, deps=None)` | every route |
| Store | `core/store.py`: `all(kind)`, `append(kind, record)`; kinds `lines`, `fixes`, `adapter`, `answers` | all state |
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
  and latency summed over the whole tool loop; each id from `x-middleware-request-id`.
- **Speakers, insights and replies** (core/insight.py, #130): every streamed and stored Line has
  `speaker: "lead" | "analyst"`. Moment lines are `"lead"`. With a video map, the quiet stretch after
  each mapped moment is filled with lines due at the last line's words / 2.7 + 2 s, until 6 s before
  the next mapped moment. Each one is a Line with `video_t`, said over a synthetic Moment
  `{...that moment, type: "Stat", outcome: "<kind>: <detail>", players: {}, detail: {speaker,
  "Partner just said": <last line>}}` with the same `idx` (a reply's outcome is "the lead answers the
  analyst, who just said: <last line>"). Its request is a line's message with the analyst's own
  system prompt (agent/analyst.md), no tools, never recorded, on `ANALYST_MODEL` (default
  claude-sonnet-5-5 with `thinking: {"type": "between_tools"}`, priced in core/stats.py; a
  model outside its prices is left out of the cost). An **insight** (`speaker: "analyst"`) carries `insight: {match_id, after_idx, n, kind, detail, heard}`, where `kind` is
  `"player profile"`, `"next to score"`, `"tally"`, `"score story"`, `"momentum"` or `"positions"`
  and `detail` is one short fact (a profile, odds or positions give one fact per insight; a
  pre-match fact names its period, such as "this season before tonight"), built only from moments up to `after_idx` and the pre-match pack. Every
  4th line in a stretch is a **reply** (`speaker: "lead"`, `reply: {..., kind: "reply"}`, no stat).
  Both are cached per (match_id, after_idx, n, v: 2) and reused by later replays; a replay makes at
  most 160 new insight and reply calls. A fix on either goes back, unrecorded, with that line's own
  Stat request.
- **Fix** (core/): `{line_id, corrected_text, reason, created_at, mubit_request_id,
  reply_matched: bool}`.
- **Match** (data/): `{match_id, sport, title?, sample: bool, youtube_id?, video_start?, embed?, peak_idx?,
  peak_video_start?}`; `sample`
  marks `data/sample/`; `youtube_id` and `video_start` are there when the match has a video map.
  `embed: false` (absent otherwise) means the video's owner blocks embedding: pages show its poster and
  a link to it on YouTube, never the player, and the commentary runs on the replay's own clock.
  `video_start` is the whole second the page starts the video at, 10 s before its first mapped moment (or 0).
  `peak_idx` (#163) is the moment "Jump to the big moment" starts at; `peak_video_start` is the video's start
  for that jump, 10 s before the first mapped moment from `peak_idx` on.
- **Video map** (data/video/): `{youtube_id, embed?, source, moments: [{idx, video_t}]}`; `idx` is a Moment's
  `idx`, `video_t` the seconds into the video of that moment's first showing, increasing with `idx`.
  Only moments matched with confidence are listed.

## HTTP

Errors: 404 not found, 409 busy or too early, 422 bad input, 503 commentator not configured.

- `GET /health` → `{status: "ok"}` (core)
- `GET /matches` → `[Match]` (core over data/)
- `POST /replays {match_id, speed>0, start_idx?}` → `{replay_id}` (core); `start_idx` (#163) starts the stream at
  that moment: earlier moments are the commentator's history, never called or sent. 422 if no such moment.
- `GET /replays/{id}/stream` → SSE: per moment `moment`, `line`, `stats` in that order; `error`
  `{code: "commentator_off_air", detail}` if the commentator fails, where `detail` is a fixed
  viewer-safe string ("Commentator is off air for a moment"), never the provider's error text (that
  goes to the server log); `end` last. A late subscriber gets the whole replay. (core)
  For a match with a video map, only mapped moments are called, the `moment` and `line` events carry
  `video_t` (seconds), and they are sent as soon as each line is ready rather than paced by `speed`:
  the page shows and speaks each line when the player reaches `video_t`.
- `GET /lines/{line_id}` → the stored Line, 404 if none (core): the live smoke checks each line it
  streamed was stored.
- `POST /lines/{line_id}/fix {corrected_text, reason?}` → Fix (core): stores the Fix in `fixes`
  beside the line, sends the correction turn (Agent below) and publishes `fixed` (the Fix), then
  `stats`, on the replay stream that carried the line; a late subscriber gets them too. 404 unknown
  line, 422 blank `corrected_text` (trimmed), 503 no commentator or the Mubit call failed (nothing
  stored, so the page can send it again).
- `POST /replays/{id}/ask {question, moment_idx?}` → Answer `{line_id, moment_idx, question, text,
  ...}` (core): a viewer's question (1-200 characters, trimmed) answered in 1-2 sentences from the
  match up to `moment_idx`, the last moment on the viewer's screen (default: the latest sent), never
  past the last moment the replay has sent, so the answer cannot spoil what is still to come. Stored
  in `answers` and spoken by `GET /lines/{line_id}/audio`, like a line; published as `answer` on the
  replay stream. Off air (the commentator call failed) it answers 200 with `{off_air: true, text:
  "Commentator is off air for a moment"}`, stores nothing and is still published. 404 unknown
  replay, 409 a question already in flight on this replay or no moment sent yet, 422 bad question.
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
  ElevenLabs voice as an earlier entry carries `same_as: <that entry's id>`, so the page lists the voice once. (core)
- `GET /lines/{line_id}/audio[?voice=<id>]` → `audio/mpeg` of the stored line (or answer) read by ElevenLabs
  in the chosen voice, or by default the voice for the line's sport. `eleven_v3` with an audio tag
  for the moment's kind (in the TTS text only, never the stored line); one retry, then
  `eleven_flash_v2_5` without the tag; `VOICE_MODEL_<SPORT>` overrides the model. The audio is
  made when the replay stores the line and cached, due before the video reaches its moment.
  404 for an unknown line or voice; 503 with no `ELEVENLABS_API_KEY` or every attempt failed,
  and the page then uses browser speech. The key never reaches the browser; each call logs
  `voice line=<id> first_byte_ms=<n> model=<model>`. (core)
- `GET /stats` → `{lines, fixes, mubit_requests, first_word_ms_p50, first_word_ms_p95,
  latency_ms_p50, latency_ms_p95, tokens_in, tokens_out, cost_per_line_usd, adapter}` (core). The
  `stats` SSE event carries the same object.
  - `cost_per_line_usd: number | null`: mean cost of the stored lines, tokens × the model's list
    price; null when no line's model has a known price.
  - `adapter: {status: "not_trained"|"training"|"ready", kept: int|null, needed, agree: int|null,
    total: int|null, cost_measurable: bool}`: `needed` is 25. `status`, `kept`, `agree` and `total`
    come from the latest `adapter` record in the store, which `python -m eval.record_adapter` appends
    from Mubit's console; before one exists, `not_trained` and nulls. `kept` is never inferred from
    stored lines, since a stored line doesn't prove Mubit kept it. `cost_measurable` is false while
    the app can't call the adapter.

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
