# Stack

| Piece | Choice | Status | Why |
|---|---|---|---|
| Language | Python 3.12+, uv | Decided | the team's starter and deploy tooling |
| Server | FastAPI + uvicorn, one process | Decided | IDEA.md ceiling: one server process |
| Store | JSON-lines files of lines and fixes; GCS objects in cloud mode | Decided | IDEA.md ceiling; a database if two producers edit at once |
| Live stream | Server-sent events (`text/event-stream`) | Decided | one-way server push, no client library |
| Model | `claude-haiku-4-5` through Mubit's Anthropic endpoint, for the moment lines (recorded) | Decided | fastest measured first word; one Mubit task |
| Analyst model | `claude-sonnet-5-5` through Mubit, unrecorded; `ANALYST_MODEL` overrides it | Decided | Haiku slipped on the stat lines' facts; unrecorded, so the moment lines stay one Mubit task |
| Voice | ElevenLabs `eleven_v3` with audio tags, `eleven_flash_v2_5` if v3 can't make it in time; browser speech only if both fail | Decided | docs/voice.md; the key stays on the server |
| Offline | `FakeProvider`, no keys, no network | Decided | `make smoke` is the merge gate |
| Check | ruff, pytest | Decided | `make check` |
| Web build | Node 22 (`node:22-slim` build stage in the Dockerfile), `npm ci && npm run build` of web/ | Decided | builds the React + Vite page (web/, Persia) into the image; the API serves `web/dist` |
| Web runtime | React 19 (`react`, `react-dom`); fonts `@fontsource/outfit`, `@fontsource/inter` | Decided | the live page (web/, Persia); fonts as docs/design.md names them, self-hosted, no font CDN on stage |
| Web tooling | Vite 8 with `@vitejs/plugin-react`, TypeScript 6, oxlint; types `@types/node`, `@types/react`, `@types/react-dom` | Decided | build, type check and lint for web/; dev only, nothing ships but `web/dist` |
| Video | YouTube IFrame Player API, loaded from youtube.com (no package) | Decided | A-6.4@2: the player's own time drives the commentary |
