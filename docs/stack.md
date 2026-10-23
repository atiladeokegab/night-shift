# Stack

| Piece | Choice | Status | Why |
|---|---|---|---|
| Language | Python 3.12+, uv | Decided | the team's starter and deploy tooling |
| Server | FastAPI + uvicorn, one process | Decided | IDEA.md ceiling: one server process |
| Store | JSON-lines files of lines and fixes; GCS objects in cloud mode | Decided | IDEA.md ceiling; a database if two producers edit at once |
| Live stream | Server-sent events (`text/event-stream`) | Decided | one-way server push, no client library |
| Model | `claude-haiku-4-5` through Mubit's Anthropic endpoint | Decided | fastest measured first word; one Mubit task |
| Offline | `FakeProvider`, no keys, no network | Decided | `make smoke` is the merge gate |
| Check | ruff, pytest | Decided | `make check` |
