# Stack

| Piece | Choice | Status | Why |
|---|---|---|---|
| Language | Python 3.12+, uv | Decided | the team's starter and deploy tooling |
| Server | FastAPI + uvicorn, one process | Decided | IDEA.md ceiling: one server process |
| Store | JSON-lines files of lines, fixes and saved voice clips; GCS objects (`google-cloud-storage`) under `STORE_URL` in cloud mode | Decided | IDEA.md ceiling; a database if two producers edit at once |
| Live stream | Server-sent events (`text/event-stream`) | Decided | one-way server push, no client library |
| Model | `claude-haiku-4-5` through Mubit's Anthropic endpoint, for the moment lines and Ask; `LEAD_MODEL` overrides it; recorded only once the number check accepts a line, and off by default on the live site (`MUBIT_RECORD=off`) | Decided | fastest measured first word; one Mubit task |
| Analyst model | `claude-sonnet-5-5` through Mubit, unrecorded; `ANALYST_MODEL` overrides it | Decided | Haiku slipped on the stat lines' facts; unrecorded, so the moment lines stay one Mubit task |
| Line check, Score check | `claude-sonnet-5-5` through Mubit, each a frozen recorded task; a producer's fix is sent to them as a training example | Decided | Haiku agreed with the answer key on 25% of a 40-line pilot, Sonnet 90%; the request is pinned by hash in its test |
| Look | `claude-haiku-4-5` through Mubit, unrecorded; `LOOK_MODEL` overrides it, `LOOKS_PER_REPLAY` caps it | Decided | one short note of a shared screen for the next line |
| Model gateway | Mubit (`https://api.mubit.ai/anthropic`) via the `anthropic` SDK; every model call goes through it; `MUBIT_FALLBACK_KEY` on a 402 | Decided | tasks and training examples from producer fixes; the app does not call an adapter |
| Budget guard | `core/guard.py`: `MAX_LIVE_REPLAYS`, `REPLAYS_PER_HOUR`, `ASKS_PER_HOUR`, `DAILY_BUDGET_USD` | Decided | past a limit, stored lines only or 429 |
| Voice | ElevenLabs `eleven_v3` with audio tags, `eleven_flash_v2_5` if v3 can't make it in time; browser speech only if both fail | Decided | docs/voice.md; the key stays on the server |
| Talk | ElevenLabs Conversational agent (`@elevenlabs/client` in web/), its custom LLM is `POST /converse/v1/chat/completions`; needs `CONVERSE_AGENT_ID`, `CONVERSE_LLM_SECRET` | Decided | the fan speaks with the commentator; off with no agent id |
| Graph | SurrealDB 2.0.0, embedded in the process (`surrealkv`, shipped in `data/graph/`) | Decided | Follow a player and team form; no service or secret; the JSON packs if it fails |
| Data | StatsBomb open data, Cricsheet, NBA play-by-play (shufinskiy/nba_data mirror, Apache-2.0), OpenF1; shipped under `data/` | Decided | real event data; credits in README.md |
| Offline | `FakeProvider`, no keys, no network | Decided | `make smoke` is the merge gate |
| Check | ruff, pytest | Decided | `make check` |
| Web build | Node 22 (`node:22-slim` build stage in the Dockerfile), `npm ci && npm run build` of web/ | Decided | builds the React + Vite page (web/, Persia) into the image; the API serves `web/dist` |
| Web runtime | React 19 (`react`, `react-dom`); fonts `@fontsource/outfit`, `@fontsource/inter` | Decided | the live page (web/, Persia); fonts as docs/design.md names them, self-hosted, no font CDN on stage |
| Web tooling | Vite 8 with `@vitejs/plugin-react`, TypeScript 6, oxlint; types `@types/node`, `@types/react`, `@types/react-dom` | Decided | build, type check and lint for web/; dev only, nothing ships but `web/dist` |
| Video | YouTube IFrame Player API, loaded from youtube.com (no package) | Decided | A-6.4@2: the player's own time drives the commentary |
| Hosting | Google Cloud Run, one instance, built by Cloud Build into Artifact Registry from the Dockerfile; keys in Secret Manager | Decided | `scripts/bootstrap.sh` once, `scripts/deploy.sh` per release |
| CI | GitHub Actions: `make smoke`, the image build, web/'s tests, lint, build and Playwright; the freeze gate | Decided | the merge gate on every PR into integration |
| Agent interface | HTTP API (docs/CONTRACT.md); no MCP server | Decided | docs/integrations.md |
