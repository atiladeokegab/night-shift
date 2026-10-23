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
| Store | `core/store.py`: `all(kind)`, `append(kind, record)`; kinds `lines`, `fixes` | all state |
| Replayer | `core/replay.py`: `run_replay` publishes `moment`, `line`, `stats` | the live stream |
| Stats | `core/stats.py`: `stats(store)` | proof panel numbers, from the store only |
| Seam to #13 | `data.matches.list_matches()`, `data.matches.load_moments(match_id)`, `agent.commentator.commentate(moment, history)` | wired by `core.app.default_deps()` |

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
- **Match** (data/): `{match_id, sport, title?, sample: bool}`; `sample` marks `data/sample/`.

## HTTP

Errors: 404 not found, 422 bad input, 503 commentator not configured.

- `GET /health` → `{status: "ok"}` (core)
- `GET /matches` → `[Match]` (core over data/)
- `POST /replays {match_id, speed>0}` → `{replay_id}` (core)
- `GET /replays/{id}/stream` → SSE: per moment `moment`, `line`, `stats` in that order; `error`
  `{detail}` if the commentator fails; `end` last. A late subscriber gets the whole replay. (core)
- `POST /lines/{line_id}/fix {corrected_text, reason}` → Fix (core, P1, not built yet)
- `GET /lines/{line_id}/audio` → `audio/mpeg` stream of the stored line read by ElevenLabs
  (`eleven_flash_v2_5`, one fixed voice). 404 for an unknown line; 503 with no `ELEVENLABS_API_KEY`
  or an upstream failure, and the page then uses browser speech. The key never reaches the browser;
  each call logs `voice line=<id> first_byte_ms=<n>`. (core)
- `GET /stats` → `{lines, fixes, mubit_requests, first_word_ms_p50, first_word_ms_p95,
  latency_ms_p50, latency_ms_p95, tokens_in, tokens_out}` (core)

## Agent

- System prompt `agent/prompt.md`, never templated. User message from one frozen template
  `agent/message.md` carrying the sport, the moment, its score and recent play.
- Tools `agent/tools.json`, sport-neutral: `get_score`, `get_player`, `get_recent_play`;
  `tool_choice: auto`; at most one tool round per line. Output: plain text, at most 20 words.
- Every model call goes through Mubit (`https://api.mubit.ai/anthropic`), model `claude-haiku-4-5`;
  one session per match in `metadata.user_id = "match-<sport>-<id>"`; no browser calls to Mubit.
  `FakeProvider` offline.
- Correction: a second turn in the line's session, "Producer correction. Reply with exactly this
  line: <text>"; `reply_matched` records whether it did.
- The commentator sees only moments up to the current one; a later event never reaches the model.

## Check

`make check` (ruff, ruff format, pytest) and `make smoke` (check, then an offline replay of each
sample match through the app with `FakeProvider`). Contract tests: `tests/acceptance/test_A_2_*.py`,
`tests/test_core_spine.py`.
