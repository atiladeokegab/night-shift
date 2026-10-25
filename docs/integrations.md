# Integrations

Every outside service, library and data source Touchline uses: what it does for the fan or the
producer, where it starts in the code, the environment variable names it reads, what happens when
it is missing or fails, the test that covers it, and how to run it with no keys. Values are never
written here, only names.

| Integration | Role | Entry point | Test |
|---|---|---|---|
| [Anthropic Claude](#anthropic-claude) | Writes the commentator's lines, the analyst's stat lines, Ask answers, "Where are we?", Line check and Score check | `agent/commentator.py:334` `commentate` | `tests/test_commentator.py` |
| [Mubit](#mubit) | The endpoint every model call goes through; groups calls into tasks; takes producer fixes as training examples | `agent/commentator.py:806` `MubitProvider` | `tests/test_commentator.py`, `tests/test_mubit_status.py`, `tests/test_linecheck_live.py`, `tests/test_scorecheck.py` |
| [ElevenLabs voice](#elevenlabs-voice) | Reads each line aloud in a commentator's voice | `core/voice.py:277` `Speaker` | `tests/test_core_voice.py`, `tests/test_voice_retry_deadline.py`, `tests/test_voice_stream_timeout.py` |
| [ElevenLabs Conversational agent](#elevenlabs-conversational-agent-talk) | Talk to the commentator by voice | `core/converse.py:310` `converse_router` | `tests/test_converse.py`, `tests/test_converse_budget.py`, `tests/test_converse_agent.py` |
| [Google Cloud](#google-cloud) | Hosting (Cloud Run), image build (Cloud Build, Artifact Registry), keys (Secret Manager), the store (GCS) | `scripts/deploy.sh`, `core/store.py:193` `open_store` | `tests/test_deploy.py`, `tests/test_core_store.py` |
| [SurrealDB, embedded](#surrealdb-embedded) | The players, teams, matches and seasons graph behind Follow a player and team form | `core/graph.py:143` `start` | `tests/test_graph.py`, `tests/test_graph_store.py`, `tests/test_graph_reads.py` |
| [Match data](#match-data) | StatsBomb, Cricsheet, NBA play-by-play, OpenF1: the events the commentator reads | `agent/feed.py`, `data/matches.py` | `tests/test_feed.py`, `tests/test_packs.py` |
| [YouTube highlights](#youtube-highlights) | The broadcast highlight the commentary is timed to | `web/src/player.ts:146` | `tests/test_video_map.py`, `web/src/player.test.ts` |
| [Agent interfaces](#agent-interfaces) | The HTTP API and the custom-LLM endpoint; there is no MCP server | `core/app.py:183` `create_app` | `tests/test_core_spine.py`, `tests/test_converse.py` |
| [GitHub Actions](#github-actions) | The merge gate on every PR into `integration` | `.github/workflows/smoke.yml` | runs `make smoke` |

## Run it offline

No keys, no network for the model or voice:

```bash
uv sync
make smoke     # ruff, pytest, then every sample match replayed with FakeProvider; the merge gate
make dev       # the server on :8000 with no keys: FakeProvider lines, browser speech, local store
```

`make smoke` blanks `MUBIT_API_KEY`, `MUBIT_FALLBACK_KEY`, `ANTHROPIC_API_KEY` and
`ELEVENLABS_API_KEY` itself, so it stays offline even when `.env` holds a real key. With no
`MUBIT_API_KEY` the commentator uses `FakeProvider` (`agent/commentator.py:879`), which reads the
event back from the data. With no `ELEVENLABS_API_KEY` the audio route answers 503 and the page
speaks with the browser's own speech. With no `MODE=cloud` the store is local files under
`STORE_DIR` (default `data`). The graph and the match data ship in the repo.

---

## Anthropic Claude

**For the fan.** Claude writes every spoken line: the lead commentator's line on each moment, the
analyst's stat lines between moments, the answer to a typed or spoken question (Ask, Talk), and the
"Where are we?" summary. Line check reads each lead line after it is said and compares four
things with its moment's data: the score, who leads, the named player's running total and the
event. Score check is the score question alone, as its own Mubit task; it is sent labelled examples
and producer fixes as training examples and does not run on live lines. A frame of a viewer's
shared screen can become a short "on screen" note for the next line (`agent/look.py`).

**Models.**

| Call | Model | Setting |
|---|---|---|
| Lead commentator, Ask | `claude-haiku-4-5` (`agent/commentator.py:31`) | `LEAD_MODEL` overrides it (`agent/commentator.py:199`); `scripts/deploy.sh` passes it to Cloud Run when set |
| Analyst stat lines | `claude-sonnet-5-5` (`agent/commentator.py:32`) | `ANALYST_MODEL` (`agent/commentator.py:214`) |
| Line check | `claude-sonnet-5-5` (`agent/linecheck.py:13`) | fixed: the request is pinned so it stays one Mubit task |
| Score check | `claude-sonnet-5-5` (`agent/scorecheck.py:12`) | fixed, as above |
| Look (shared screen) | `claude-haiku-4-5` (`agent/look.py:15`) | `LOOK_MODEL` (`agent/look.py:33`); `LOOKS_PER_REPLAY` caps it (`core/look.py:40`) |

**Entry points.** `commentate` (`agent/commentator.py:334`), `answer` for Ask
(`agent/commentator.py:683`), `status` for "Where are we?" (`agent/status.py:174`), Line check
`live_check` (`agent/linecheck.py:106`), Score check `teach` (`agent/scorecheck.py:83`), Look `see`
(`agent/look.py:74`). The routes are `POST /replays/{replay_id}/ask` (`core/app.py:574`) and the
replay stream.

**How it is called.** The Anthropic Python SDK (`anthropic` in `pyproject.toml`), with its base URL
set to Mubit (next section). The app holds no Anthropic key of its own: the key is `MUBIT_API_KEY`.

**When it is missing or fails.** Every line goes through the number check before it is said
(`core/insight.py:1781` `checked`). A line that contradicts the data, or no reply at all, is replaced
by a line built only from the moment's data (`core/fallback.py`), marked `fallback` and queued for
the producer. An Ask with no usable answer says "No word on that yet" and the data's own line
(`agent/commentator.py:727`). Offline, `FakeProvider` stands in.

**Tests.** `tests/test_commentator.py`, `tests/test_analyst_check.py`, `tests/test_core_ask.py`,
`tests/test_status.py`, `tests/test_look.py`, `tests/test_fallback.py`, `tests/test_event_check.py`.

**No keys.** `make smoke`, or `uv run pytest tests/test_commentator.py -q`.

## Mubit

**For the producer.** Every model call goes through Mubit's Anthropic-compatible endpoint
(`MUBIT_URL = "https://api.mubit.ai/anthropic"`, `agent/commentator.py:36`). Mubit groups calls with
byte-identical instructions, tools, output format and model into one task, which is why the Line
check and Score check requests are pinned by hash in their tests. When a producer fixes a line,
the fix is sent to Mubit as a training example, and the fix is said on later replays of that match
(it rides in the next requests' prompt, `agent/commentator.py:167` `match_fixes`).

**Entry points.**

- `MubitProvider` (`agent/commentator.py:806`): the Anthropic SDK pointed at Mubit, streamed so the
  first word can be timed. `default_provider` (`agent/commentator.py:480`) makes it when
  `MUBIT_API_KEY` is set, else `FakeProvider`.
- Recording: `MUBIT_RECORD=off` sends `x-middleware-record: off`, so a call is paid for but not
  recorded for training (`agent/commentator.py:486`). `scripts/deploy.sh` sets it `off` on the live
  site by default; `MUBIT_RECORD=on make deploy` records again. A line is first made unrecorded and
  only one the number check accepted is sent again to be recorded (`agent/commentator.py:458`
  `recorded`).
- Producer fixes: `POST /lines/{line_id}/fix` (`core/app.py:456`), locked by `PRODUCER_TOKEN`
  (`core/app.py:66`). A fix whose reason is a wrong score, player or fact goes to Line check's
  `teach` (`agent/linecheck.py:120`); any fix the data can label goes to Score check's `teach`
  (`agent/scorecheck.py:83`). Both send on the owner's key (`MUBIT_FALLBACK_KEY`) when it is set,
  recorded whatever `MUBIT_RECORD` says (`agent/commentator.py:497` `correction_provider`); without
  it, on the lines' provider when that records. The correction ledger (`core/ledger.py`) lists
  every example sent, with its Mubit session and request id.
- Line check on each line: after a line the number check accepted is said, the replay asks Line
  check for a second opinion (`core/replay.py:127` `second_opinion`). A flag only sends the line to
  the producer's queue; it never stops a line. Lines from held-out matches are never recorded, so
  the test set never trains.
- Adapter records: Mubit's console is read by hand and written with `eval/record_adapter.py`
  (`uv run python -m eval.record_adapter --help` lists the fields), and
  `data/mubit_console.json` holds the dated readings, newest first. `/stats` shows those records; nothing probes Mubit
  live for them.

**Where it stands.** Commentary runs on Claude. The app does not call an adapter. Mubit's "Check one
line of 2" task (one of our two line-checking tasks, Line check or Score check; the console cuts the
name short) shows 94.6% for its first version, testing v1, in testing (console read by hand, 25 Oct
2026 06:27 UTC, recorded in `data/mubit_console.json`).

**Environment.** `MUBIT_API_KEY` (the key every call uses), `MUBIT_FALLBACK_KEY` (the owner's key:
the commentator moves to it if the first key runs out of credit, a 402, `agent/commentator.py:842`;
fixes are sent on it), `MUBIT_RECORD` (`on` or `off`). Scripts under `eval/` also read
`MUBIT_ADAPTER_MODEL` (`eval/agreement.py:271`).

**When it is missing or fails.** No `MUBIT_API_KEY`: `FakeProvider`, and the server logs
"MUBIT_API_KEY unset: Mubit is off, lines use the fallback" (`core/app.py:191`). A failed call:
`/health` and `/stats` report `mubit: degraded` with the reason, such as `503 engine_unavailable`
(`agent/commentator.py:788` `mubit_status`), and the line falls back as above. Live Line check and
the fix examples make no call offline.

**Spend.** The budget guard (`core/guard.py:143` `Guard`) caps replays generating new lines at once
(`MAX_LIVE_REPLAYS`), replay starts and Asks per visitor an hour (`REPLAYS_PER_HOUR`,
`ASKS_PER_HOUR`), and the day's model and voice spend (`DAILY_BUDGET_USD`). Past a limit a replay
plays the lines already stored, with no model call, or the route answers 429. The README states the
cost as about $0.41 a replay, voice included, a running mean over 133 replays
(`eval/live_stats_2026-10-25.json`).

**Tests.** `tests/test_commentator.py` (provider, `MUBIT_RECORD`, the 402 move),
`tests/test_mubit_status.py`, `tests/test_linecheck.py`, `tests/test_linecheck_live.py`,
`tests/test_scorecheck.py`, `tests/test_core_fix.py`, `tests/test_core_ledger.py`,
`tests/test_eval_record_adapter.py`, `tests/test_guard.py`.

**No keys.** `uv run pytest tests/test_linecheck.py tests/test_scorecheck.py tests/test_mubit_status.py -q`.

## ElevenLabs voice

**For the fan.** Each stored line is read aloud as soon as it is made, so the audio is ready before
the video reaches its moment. Each sport has its own lead voice and an analyst voice
(`core/voice.py:46` `VOICES`); an audio tag sets the delivery for the moment's kind.

**Entry points.** `Speaker` (`core/voice.py:277`) makes the clips; `voice_router`
(`core/voice.py:698`) serves `GET /voices` and `GET /lines/{line_id}/audio`. A clip, once made, is
saved to the store (`core/voice.py:507` `save_clip`) and served again with no ElevenLabs call, on
any instance (`core/voice.py:736`).

**Models and fallbacks.** `eleven_v3` with audio tags, one retry, then `eleven_flash_v2_5`, then one
short flash call more after a timeout or upstream error (`core/voice.py:27`). After a 429 no call
is made for 20 seconds and queued lines go to subtitles (`core/voice.py:38`). Backup keys are tried
once the main key's quota is gone (`core/voice.py:220` `backup_keys`). With no key, or every
attempt failed, the route answers 503 and the page speaks with the browser's speech
(`web/src/useSpeech.ts`).

**Environment.** `ELEVENLABS_API_KEY`, `ELEVENLABS_API_KEY_FALLBACKS` (comma-separated backups),
`VOICE_<SPORT>`, `VOICE_MODEL_<SPORT>`, `VOICE_LABEL_<SPORT>` (per-sport voice, model and the name
the page shows; `docs/voice.md`).

**Tests.** `tests/test_core_voice.py`, `tests/test_voice_retry_deadline.py`,
`tests/test_voice_stream_timeout.py`, `tests/test_cached_first.py` (saved clips), `web/src/voice.test.ts`.

**No keys.** `uv run pytest tests/test_core_voice.py -q`; `make dev` plays with browser speech.

## ElevenLabs Conversational agent (Talk)

**For the fan.** Talk to the commentator: the fan speaks in the browser with an ElevenLabs agent
(`@elevenlabs/client`, `web/src/components/Converse.tsx`). The agent's custom LLM is Touchline's
own endpoint, which answers each turn through the Ask path (Claude through Mubit, unrecorded), from
the match cut at the moment the conversation started.

**Entry points.** `GET /converse/{sport}/{match_id}/token` hands the page a signed URL, so the key
stays on the server (`core/converse.py:314`). `POST /converse/v1/chat/completions` is the agent's
custom LLM, checked against a shared bearer secret (`core/converse.py:355`).
`scripts/converse_agent.py` creates or updates the agent and stores the secret in ElevenLabs.

**Environment.** `ELEVENLABS_API_KEY`, `CONVERSE_AGENT_ID`, `CONVERSE_LLM_SECRET`.

**When it is missing or fails.** Any of the three unset: the token route answers 503
"conversation not configured" and the Talk button stays off. Over the day's budget: 503, off air
for today. `scripts/deploy.sh` mounts the secret only when `CONVERSE_AGENT_ID` is set.

**Tests.** `tests/test_converse.py`, `tests/test_converse_budget.py`,
`tests/test_converse_tool_check.py`, `tests/test_converse_agent.py`, `web/src/converse.test.ts`.

**No keys.** `uv run pytest tests/test_converse.py -q`;
`uv run python scripts/converse_agent.py --dry-run` prints the agent's config and calls nothing.

## Google Cloud

**For the fan.** The live site runs on Cloud Run, and the store keeps every line, fix and voice
clip across redeploys.

**Entry points.**

- `scripts/bootstrap.sh` (once per project, `make bootstrap`): enables Cloud Run, Cloud Build and
  Artifact Registry, creates the `cloud-run-source-deploy` repository, the state bucket, the
  secrets in Secret Manager and a `deployer` service account with only the roles a deploy needs.
- `scripts/deploy.sh` (`make deploy`): `gcloud run deploy --source .`, which builds the
  `Dockerfile` with Cloud Build into Artifact Registry. It mounts the keys from Secret Manager
  (`mubit-api-key`, `elevenlabs-api-key`, `producer-token`, and `converse-llm-secret` with Talk),
  checks each mounted version is enabled before the build, and runs one instance
  (`--max-instances 1`, `MIN_INSTANCES` default 1, kept warm through judging) with CPU on between
  requests. After the deploy it runs the live smoke against the new URL.
- The store: `open_store` (`core/store.py:193`). `MODE=cloud` needs `STORE_URL=gs://bucket/prefix`
  and uses `GcsStore` (`core/store.py:102`, `google-cloud-storage`): JSON-lines objects and saved
  voice clips under that prefix. Otherwise `Store` writes files under `STORE_DIR`.

**Environment.** Runtime: `MODE`, `STORE_URL`, `STORE_DIR`, the secrets above. Deploy:
`PROJECT`, `REGION`, `SERVICE`, `STATE_BUCKET`, `MIN_INSTANCES`, `DEPLOY_AS_SELF`,
`ELEVENLABS_FALLBACK_VERSION`, `MUBIT_FALLBACK_VERSION`, `DAILY_BUDGET_USD`, `LEAD_MODEL`,
`CONVERSE_AGENT_ID`, `MUBIT_RECORD`.

**When it is missing or fails.** `MODE=cloud` with no `gs://` `STORE_URL` refuses to start. A clip
that fails to save is still played; only the saved copy is lost. A missing secret version stops the
deploy before the build.

**Tests.** `tests/test_core_store.py`, `tests/test_deploy.py`, `tests/test_cached_first.py`; CI's
`image` job builds the image and imports the app inside it.

**No keys.** Local mode is the default: `make dev`. `make load STORE=gcs` runs `GcsStore` over a
bucket stand-in with GCS-like latency.

## SurrealDB, embedded

**For the fan.** Follow a player, team form and head-to-head read a graph of players, teams,
matches and seasons: 620 football matches (612 from StatsBomb in four competition-seasons, 8 NWSL
2018 results from `data/results/`), plus the other sports' shipped packs and samples.

**Entry point.** `core/graph.py`: `start` and `start_soon` (`core/graph.py:143`, called once per
process from `core/app.py:193`) load it; `pack`, `team_form`, `head_to_head` and `player_season`
read it. It runs in this process (`surrealdb==2.0.0`, `mem://` and `surrealkv://`): no service,
secret or setting. The shipped store is `data/graph/`; `scripts/build_graph.py` rebuilds it.

**Environment.** None.

**When it is missing or fails.** Any engine or query error logs its type and returns None, and the
caller reads the JSON packs under `data/packs/` instead; the page never breaks on it.

**Tests.** `tests/test_graph.py`, `tests/test_graph_store.py`, `tests/test_graph_reads.py`,
`tests/test_teams.py`.

**No keys.** Always offline: `uv run pytest tests/test_graph.py -q`.

## Match data

**For the fan.** The commentator reads the event feed, not the video. Each match is a list of
moments built from real event data and shipped under `data/sample/`, with a pre-match pack under
`data/packs/`.

| Source | Sport | Loader | Licence or terms |
|---|---|---|---|
| [StatsBomb open data](https://github.com/statsbomb/open-data) | Football | `agent/feed.py:78` `statsbomb_matches`, `statsbomb_events` | used under StatsBomb's open data licence |
| [Cricsheet](https://cricsheet.org) | Cricket, ball by ball | `agent/feed.py:248` `cricsheet_zip` | Cricsheet's terms |
| stats.nba.com play-by-play, via [shufinskiy/nba_data](https://github.com/shufinskiy/nba_data) | Basketball | `agent/feed.py:373` `nba_rows` | the mirror is Apache-2.0 |
| [OpenF1](https://openf1.org) | F1 timing | `agent/feed.py:509` `openf1` | OpenF1's terms |
| Wikipedia, 2018 Orlando Pride season | NWSL 2018 results StatsBomb does not cover | `data/results/nwsl-2018-orlando.json` | the source URL is in the file |

`data/matches.py` names each match and where its data came from. Every fetch in `agent/feed.py`
has a timeout (`agent/feed.py:57` `_fetch`) and the downloaded data is treated as untrusted.

**Environment.** None.

**When it is missing or fails.** The app reads only the shipped files; it fetches nothing at run
time.

**Tests.** `tests/test_feed.py`, `tests/test_packs.py`, `tests/test_long_tail.py`.

**No keys.** The sample matches ship in the repo; `make smoke` replays each one.

## YouTube highlights

**For the fan.** Each match plays over a broadcast highlight on YouTube, embedded and muted, never
downloaded or rehosted. The player's own time drives when each line is said.

**Entry point.** `web/src/player.ts:146` loads the YouTube IFrame Player API from youtube.com (no
package). `data/video/<sport>-<match>.json` maps each moment to its time in the video and names the
upload.

**Environment.** None.

**When it is missing or fails.** A moment with no video time is spoken as it arrives
(`core/voice.py:33`).

**Tests.** `tests/test_video_map.py`, `tests/test_core_jump.py`, `web/src/player.test.ts`.

**No keys.** `make dev` and open a match; the video needs the network, the commentary does not.

## Agent interfaces

There is no MCP server. Agents and other programs reach Touchline over HTTP:

- The public API in `docs/CONTRACT.md` (`core/app.py:183` `create_app`): replays and their
  server-sent event stream, Ask, `GET /health`, `GET /stats`, and the producer's fix route.
- `POST /converse/v1/chat/completions` (`core/converse.py:355`): a chat-completions endpoint the
  ElevenLabs agent calls as its custom LLM, behind `CONVERSE_LLM_SECRET`.

**Tests.** `tests/test_core_spine.py`, `tests/test_core_stats.py`, `tests/test_converse.py`.

## GitHub Actions

**For the team.** Every PR into `integration` runs the same checks the lead runs.

`.github/workflows/smoke.yml`:

- `smoke`: `make smoke`, which is `ruff check`, `ruff format --check`, `pytest`, then every sample
  match replayed offline with `FakeProvider`. No secrets.
- `image`: builds the `Dockerfile` Cloud Run will run and imports `core.main` inside it, so a
  dependency missing from the image fails here, not after deploy.
- `web`: in `web/`, `npm test`, `npm run lint`, `npm run build`, then Playwright browser tests
  (axe, and the voice heard) against the match server with no keys.

`.github/workflows/freeze-gate.yml`: after code freeze (`FREEZE_AT`, a repository variable) only
PRs labelled `fix` may merge.

**No keys.** `make smoke`; `cd web && npm ci && npm test`.
