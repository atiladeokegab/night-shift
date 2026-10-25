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
| [ARCHITECTURE.md](ARCHITECTURE.md) | How Touchline is built, from the code: one replayed line end to end, C4 levels 1 to 4, the module map, Mubit and Claude, deploy and ops, and the scale plan, which is not built | judge, developer, agent |
| [CONTRACT.md](CONTRACT.md) | The shared shapes, HTTP endpoints, agent tools and check every area builds against | developer, agent |
| [PRD.md](PRD.md) | The requirements (PRD v6); each has an ID such as A-6.4 that the tests checking it name | judge, developer, agent |
| [build-log.md](build-log.md) | How much the team shipped during the event, in what order and how each piece was checked; every number comes with the command that reproduces it | judge, agent |
| [decisions.md](decisions.md) | Each design decision: what we decided, the problem it answered, the reasoning with its evidence, what we rejected, what it costs, and where it lives in the code | judge, developer, agent |
| [demo.md](demo.md) | The demo film's script, timings, the jump to each big moment and what to do if something fails | judge |
| [design.md](design.md) | The page's design spec: look, layout, components, flow, states and copy (as of PRD v2) | developer |
| [evidence.md](evidence.md) | The correction loop with real examples, how Mubit is used, how the check was measured, keyboard and screen reader support, and the source of every README figure | judge, agent |
| [expo.md](expo.md) | The live demo on the deployed site, step by step in the film's order | judge |
| [features.md](features.md) | Every feature for the fan, the producer and engineering, each with its live link, code and test, plus screenshots and the numbers | judge, fan, developer |
| [feedback.md](feedback.md) | Each point from the judge's second check-in and the PR or file where it landed | judge |
| [integrations.md](integrations.md) | Every outside service, library and data source: its role, entry point, environment variable names, what happens when it fails, its test, and how to run with no keys | judge, developer, agent |
| [stack.md](stack.md) | Each technology choice and why: FastAPI, JSON-lines store, SSE, Claude models, ElevenLabs | developer |
| [usefulness.md](usefulness.md) | Why Touchline is useful: primary sources showing the need for described matches, what the product does today for each need, the buyer and cost proposition, and what would prove usefulness beyond the prototype | judge, agent |
| [voice.md](voice.md) | The commentator's voice: ElevenLabs models, audio tags, timing, voices per role and sport | fan, developer |

## Images and pages

| File | What it is | For |
|---|---|---|
| [banner.svg](banner.svg) | The repo README's banner | judge, fan |
| [architecture/c4.py](architecture/c4.py) | The script that draws the four C4 diagrams below; the command to rerun it is at the end of ARCHITECTURE.md | developer, agent |
| [architecture/c4_context.png](architecture/c4_context.png) | C4 level 1: Touchline, its users and the services it calls | judge, developer, agent |
| [architecture/c4_container.png](architecture/c4_container.png) | C4 level 2: the Cloud Run service, its store and the build | judge, developer, agent |
| [architecture/c4_component.png](architecture/c4_component.png) | C4 level 3: the replay pipeline's components, from moments to the number check, voice, Line check, fix, Ask and stats | developer, agent |
| [architecture/c4_code.png](architecture/c4_code.png) | C4 level 4: the classes and functions one replayed line passes through | developer, agent |
| [img/about-mubit.png](img/about-mubit.png) | Screenshot: the About page's flow diagram, from match data through the number check, retry and voice to a producer's fix going to Mubit's Score check training | judge |
| [img/ask.png](img/ask.png) | Screenshot: an Ask question and its answer during Kobe's 81 | judge, fan |
| [img/auto-fixed.png](img/auto-fixed.png) | Screenshot, cropped to the Lines card: a Kobe's 81 line tagged Auto-fixed, whose first try failed the number check and whose retry was said | judge |
| [img/eyes-closed.png](img/eyes-closed.png) | Screenshot: India v Pakistan with Close your eyes on, the picture black with only the line and the score bar | judge, fan |
| [img/fix.png](img/fix.png) | Screenshot: the producer's Fix this line sheet | judge, fan |
| [img/follow.png](img/follow.png) | Screenshot: following a player on the live page | judge, fan |
| [img/home.png](img/home.png) | Screenshot: the home page at 1440 px with the match tiles | judge, fan |
| [img/live.png](img/live.png) | Screenshot: the live match page | judge, fan |
| [img/phone.png](img/phone.png) | Screenshot: the live page on a 390 px phone during Argentina v France | judge, fan |
| [img/prs-per-hour.svg](img/prs-per-hour.svg) | Chart for the build log: merged pull requests per hour, UTC | judge |
| [img/review.png](img/review.png) | Screenshot: the producer's Review queue of flagged lines, each with a Fix this line button | judge |
| [img/shotmap.png](img/shotmap.png) | Screenshot: a player's shot map sheet | judge, fan |
| [img/side-by-side.png](img/side-by-side.png) | Screenshot from earlier in the event: the big model's recorded lines beside a commentator version still in training | judge |
| [img/wall.png](img/wall.png) | Screenshot: the home page's wall of matches | judge, fan |
| [media/demo.gif](media/demo.gif) | The README's 9-second recording of lines being called on the live page | judge, fan |
| [mockup/index.html](mockup/index.html) | The clickable design mockup of every screen and state; open it in a browser | developer |
