# docs: what each file is and who it is for

The product overview is the [repo README](../README.md); an agent reading the repo cold can start at
[llms.txt](../llms.txt). Audiences: **judge** (assessing the entry), **fan** (using Touchline),
**developer** (changing the code), **agent** (an AI reading or working in the repo).

## Verify our claims in 5 commands

No keys, accounts or model calls needed. From the repo root, with [uv](https://docs.astral.sh/uv/)
and `make`:

```bash
make smoke                                                       # lint, the full test suite, then every sample match replayed offline with a fake model
uv run pytest -q tests/test_insight.py tests/test_scorecheck.py  # the number check and the Score check task's labels and request
uv run pytest -q tests/test_readme_numbers.py tests/test_readme_claims.py  # README figures and Mubit call sites traced to their source
curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/health       # the live service and its Mubit connection
curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/stats        # the live Proof card's figures: lines, fixes, latency, cost, Score check counts
```

## Documents

| File | What it is | For |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | What runs today on Cloud Run as a C4 container diagram, and the scale plan, which is not built | judge, developer, agent |
| [CONTRACT.md](CONTRACT.md) | The shared shapes, HTTP endpoints, agent tools and check every area builds against | developer, agent |
| [PRD.md](PRD.md) | The requirements (PRD v6); each has an ID such as A-6.4 that the tests checking it name | judge, developer, agent |
| [demo.md](demo.md) | The demo film's script, timings, the jump to each big moment and what to do if something fails | judge |
| [design.md](design.md) | The page's design spec: look, layout, components, flow, states and copy (as of PRD v2) | developer |
| [evidence.md](evidence.md) | The correction loop with real examples, how Mubit is used, how the check was measured, keyboard and screen reader support, and the source of every README figure | judge, agent |
| [expo.md](expo.md) | The live demo on the deployed site, step by step in the film's order | judge |
| [features.md](features.md) | Every feature with its code and tests, and where the product goes next | judge, fan, developer |
| [feedback.md](feedback.md) | Each point from the judges' second check-in and the PR or file where it landed | judge |
| [integrations.md](integrations.md) | Every outside service, library and data source: its role, entry point, environment variable names, what happens when it fails, its test, and how to run with no keys | judge, developer, agent |
| [stack.md](stack.md) | Each technology choice and why: FastAPI, JSON-lines store, SSE, Claude models, ElevenLabs | developer |
| [voice.md](voice.md) | The commentator's voice: ElevenLabs models, audio tags, timing, voices per role and sport | fan, developer |

## Images and pages

| File | What it is | For |
|---|---|---|
| [banner.svg](banner.svg) | The repo README's banner | judge, fan |
| [architecture/c4_context.png](architecture/c4_context.png) | C4 context diagram drawn at planning time: Touchline, its users and external services | judge, developer |
| [architecture/c4_container.png](architecture/c4_container.png) | C4 container diagram drawn at planning time; the current one is in ARCHITECTURE.md | judge, developer |
| [architecture/c4_component.png](architecture/c4_component.png) | C4 component diagram drawn at planning time: the match server's planned modules | developer |
| [img/ask.png](img/ask.png) | Screenshot: an Ask question and its answer during Kobe's 81 | judge, fan |
| [img/fix.png](img/fix.png) | Screenshot: the producer's Fix this line sheet | judge, fan |
| [img/follow.png](img/follow.png) | Screenshot: following a player on the live page | judge, fan |
| [img/live.png](img/live.png) | Screenshot: the live match page | judge, fan |
| [img/shotmap.png](img/shotmap.png) | Screenshot: a player's shot map sheet | judge, fan |
| [img/side-by-side.png](img/side-by-side.png) | Screenshot from earlier in the event: the big model's recorded lines beside a commentator version still in training | judge |
| [img/wall.png](img/wall.png) | Screenshot: the home page's wall of matches | judge, fan |
| [media/demo.gif](media/demo.gif) | The README's 9-second recording of lines being called on the live page | judge, fan |
| [mockup/index.html](mockup/index.html) | The clickable design mockup of every screen and state; open it in a browser | developer |
