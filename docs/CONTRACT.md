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
| Store | `core/store.py`: `all(kind)`, `append(kind, record)`; kinds `lines`, `fixes`, `adapter` | all state |
| Replayer | `core/replay.py`: `run_replay` publishes `moment`, `line`, `stats` | the live stream |
| Stats | `core/stats.py`: `stats(store)` | proof panel numbers, from the store only |
| Seam to #13 | `data.matches.list_matches()`, `data.matches.load_moments(match_id)`, `agent.commentator.commentate(moment, history)` | wired by `core.app.default_deps()` |
| Video map | `data.matches.video_map(match_id)` over `data/video/<sport>-<match_id>.json` | a demo match's YouTube video (A-6.4) |

Store: JSON-lines files under `STORE_DIR` (default `data/`). `MODE=cloud` keeps them as GCS objects
and refuses to start without `STORE_URL=gs://bucket/prefix`.

## Shapes

- **Moment** (data/): `{sport: "football"|"cricket", match_id, idx, period, clock, type, team,
  players: {role: name}, outcome, score: {home, away} | {runs, wickets, target?}, x?, y?, detail: {}}`.
  `clock` is `"mm:ss"` for football and `"over.ball"` for cricket; `period` is the half or the
  innings; roles e.g. `shooter`, `keeper` / `batter`, `bowler`, `fielder`; `detail` holds sport
  fields (runs, extras, wicket kind, xG, card); `x, y` on StatsBomb's 120 x 80 when known.
- **Line** (agent/): `{line_id, sport, match_id, moment_idx, text, model, latency_ms,
  first_word_ms, tokens_in, tokens_out, mubit_request_ids: [], tool_calls: [], created_at}`; tokens
  and latency summed over the whole tool loop; each id from `x-middleware-request-id`.
- **Fix** (core/): `{line_id, corrected_text, reason, created_at, mubit_request_id,
  reply_matched: bool}`.
- **Match** (data/): `{match_id, sport, title?, sample: bool, youtube_id?}`; `sample` marks
  `data/sample/`; `youtube_id` is there when the match has a video map.
- **Video map** (data/video/): `{youtube_id, source, moments: [{idx, video_t}]}`; `idx` is a Moment's
  `idx`, `video_t` the seconds into the video of that moment's first showing, increasing with `idx`.
  Only moments matched with confidence are listed.

## HTTP

Errors: 404 not found, 422 bad input, 503 commentator not configured.

- `GET /health` → `{status: "ok"}` (core)
- `GET /matches` → `[Match]` (core over data/)
- `POST /replays {match_id, speed>0}` → `{replay_id}` (core)
- `GET /replays/{id}/stream` → SSE: per moment `moment`, `line`, `stats` in that order; `error`
  `{detail}` if the commentator fails; `end` last. A late subscriber gets the whole replay. (core)
  For a match with a video map, only mapped moments are called, the `moment` and `line` events carry
  `video_t` (seconds), and they are sent as soon as each line is ready rather than paced by `speed`:
  the page shows and speaks each line when the player reaches `video_t`.
- `POST /lines/{line_id}/fix {corrected_text, reason?}` → Fix (core): stores the Fix in `fixes`
  beside the line, sends the correction turn (Agent below) and publishes `fixed` (the Fix), then
  `stats`, on the replay stream that carried the line; a late subscriber gets them too. 404 unknown
  line, 422 blank `corrected_text` (trimmed), 503 no commentator or the Mubit call failed (nothing
  stored, so the page can send it again).
- `GET /stage` → the backup live page (`core/stage.html`, static HTML over the routes here) (core)
- `GET /voices` → `[{id, label, default_for: "cricket"|"football"|null, lang: "en-IN"|"en-GB"}]`, the page's voice
  setting: an Indian English commentator for cricket, a British one for football; `lang` is
  the BCP 47 tag the browser-speech fallback uses. `VOICE_<SPORT>` picks a sport's default: an id
  here, or a raw ElevenLabs voice id, listed as `<sport>-pick` (docs/voice.md). (core)
- `GET /lines/{line_id}/audio[?voice=<id>]` → `audio/mpeg` of the stored line read by ElevenLabs
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
  `tool_choice: auto`; at most one tool round per line. Output: plain text, at most 20 words.
- Every model call goes through Mubit (`https://api.mubit.ai/anthropic`), model `claude-haiku-4-5`;
  one session per match in `metadata.user_id = "match-<sport>-<id>"`; no browser calls to Mubit.
  `FakeProvider` offline.
- Correction (`agent.commentator.correct`): the line's original request (same prompt, tools, model
  and `metadata.user_id`, so the same Mubit task and session) plus the line as the assistant turn
  and "Producer correction. Reply with exactly this line: <text>"; `reply_matched` records whether
  the reply was exactly that line. Mubit has no feedback API, so this turn is the training signal.
- The commentator sees only moments up to the current one; a later event never reaches the model.

## Check

`make check` (ruff, ruff format, pytest) and `make smoke` (check, then an offline replay of each
sample match through the app with `FakeProvider`). Contract tests: `tests/acceptance/test_A_2_*.py`,
`tests/test_core_spine.py`.
