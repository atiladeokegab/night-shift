<div align="center">

<img src="docs/banner.svg" alt="Banner: the word Touchline. in amber over a drawn night stadium with floodlights and a green pitch, the tagline A live AI commentator for matches nobody calls, and a red ON AIR pill." width="100%">

<br>

[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-live%20stream-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Mubit](https://img.shields.io/badge/Mubit-trains%20the%20commentator-FFB547)](https://mubit.ai)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-commentator%20voice-000000?logo=elevenlabs&logoColor=white)](https://elevenlabs.io)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-deployed-4285F4?logo=googlecloud&logoColor=white)](https://cloud.google.com/run)

**One live AI commentator for football and cricket, trained on its own corrected calls.**

[**For judges**](#for-judges) · [**What it does**](#what-it-does) · [**Requirements (PRD)**](docs/PRD.md) · [**Run it**](#run-it) · [**How it uses Mubit**](#how-it-uses-mubit) · [**Team**](#team)

<img src="docs/img/live.png" alt="The live page, from the design mockup. A drawn night stadium stands in for the official highlights video. Top left, the score bar reads ESP 1-0 ENG, 28:29, 1st half, REPLAY. Top right, a red ON AIR pill names the British commentator. In the lower third, the moment tag 28:29 GOAL sits above the large subtitle: Olga Carmona! Low across Earps and in! Spain lead the World Cup final! Under it, a dock with Fixtures, a Football and Cricket switch and Voice: British, and a video timeline with a small Synced to video label. On the right, a Lines card lists each line with its clock, its first-word time and a Fix button, and a Proof card shows first word p50 and p95, cost per line, lines, fixes and the adapter's result." width="100%">

<sub>The live page as designed (<code>docs/mockup/index.html</code>). In the product the official
highlights play where the drawn stadium is; the numbers in this picture are samples, not measurements.</sub>

</div>

---

Built at Night Shift: Mubit Hackathon, London, 23 to 25 October 2026. Track: Own your intelligence layer.
Requirements: [docs/PRD.md](docs/PRD.md); each one has an ID such as A-6.4 and a test.

## For judges

Staging URL: <https://night-shift-staging-5zvig7nbvq-ew.a.run.app> (Cloud Run, real Mubit calls). Every number below was read from that service or
from our traffic log on 23 October 2026; anything not yet measured says so.

| Criterion | Evidence | Measured | Check it |
|---|---|---|---|
| Use of Mubit | Every model call goes through Mubit's Anthropic endpoint (`claude-haiku-4-5`), one session per match, one task for every sport. The traffic runner replays real matches through it | 16 real matches (8 football, 8 cricket), 160 lines. 38 Mubit requests counted on staging by their Mubit request ids | `curl -s https://night-shift-staging-5zvig7nbvq-ew.a.run.app/stats` (field `mubit_requests`) |
| Use of Mubit: a correction becomes a model update | A producer's fix goes back through the same Mubit task and session (A-4.1) | To be measured: the fix route is not built yet | Not yet available |
| Usefulness | Most matches have no commentator; Touchline calls real football and cricket matches from real event data (StatsBomb, Cricsheet) | 2 demo matches served on staging | `curl -s https://night-shift-staging-5zvig7nbvq-ew.a.run.app/matches` |
| Technical execution | FastAPI server, durable store on Cloud Storage, server-sent event stream, an offline test suite and a live smoke test on every deploy | Staging health: ok. Live smoke on deploy: 36 moments, 36 lines | `curl -s https://night-shift-staging-5zvig7nbvq-ew.a.run.app/health` |
| Demo | A 3-minute live demo on the deployed URL: the World Cup final called in a British voice, one live fix, then India v Pakistan in an Indian voice | To be recorded | Not yet available |
| Track: quality, cost and latency side by side | The proof panel and `GET /stats` show the big model and our trained commentator on the same held-out moments | First word p50 524 ms, p95 789 ms; full line p50 835 ms, p95 1,051 ms (big model, 36 lines on staging). Cost per line and the trained model's agreement: to be measured | `curl -s https://night-shift-staging-5zvig7nbvq-ew.a.run.app/stats` |

## What it does

Status as of 23 October 2026, 22:00 UTC.

| Capability | What it means | Status |
|---|---|---|
| Football and cricket | Real matches from StatsBomb open data and Cricsheet, replayed moment by moment | Running on staging |
| Basketball, F1 and the 2022 World Cup final (Messi v Mbappé) | Iconic extra screens from real play-by-play and timing data, called by the same commentator (A-10) | Planned, after the core |
| Commentary synced to the official highlights | The page plays the match's official highlights (embedded YouTube, muted). The player's own clock drives the commentary, so a line is shown and spoken when its moment plays and never runs ahead of the picture (A-6.4) | In progress |
| Emotional commentary | A goal, a saved penalty, a six or a wicket is called with a broadcast commentator's excitement, at most 20 words, with every name and score right (A-3.6) | In progress |
| Voice setting | Cricket defaults to an Indian commentator voice, football to a British one; a change applies from the next line without a reload (A-6.3). Voices from ElevenLabs, with the browser's speech as a fallback | In progress |
| Producer fix loop | A producer corrects or rejects a line in one tap; the fix is stored beside the original and sent back through the same Mubit task and session (A-4.1) | Planned |
| Proof panel | First-word latency p50 and p95, cost per line, lines, fixes and the trained model's result, matching `GET /stats` (A-7.1) | In progress |
| One Mubit task for every sport | One system prompt, one message template, one tool set, one model; the sport goes in the message (A-1.2, A-10.3) | Built |
| Facts from tools, not memory | The commentator looks up the score, the player and recent play with tools, and never sees anything later in the match (A-1.4, A-3.1) | Built |

## The problem

Somewhere tonight a county cricket chase goes to the last ball, and nobody calls it. A women's
league side scores the goal of its season, and the stream is silent. Most matches in most sports are
played like this: grassroots and lower-league football, most of the women's game, club and county
cricket. Fans following a stream or a live score get a bare ticker, or nothing.

A big model could commentate them. But it is too slow to call a moment while the moment is still on
screen, and too expensive to run for every moment of every match.

**Touchline** is one live AI commentator for every sport it covers. It plays a match's official highlights,
and as each key moment plays it calls it in one short, emotional line, read aloud in a commentator's
voice and shown as a large subtitle. A producer fixes any line that's wrong, the fix goes back through
Mubit, and Mubit trains a smaller commentator. The aim is that it calls the same moments as well as
the big model, at lower cost; the table below shows how far that is measured.

## The demo, in one line

The 2023 Women's World Cup final plays on screen and Touchline calls each moment aloud, in a British
voice, about a second after it happens; the producer fixes one wrong line on stage; our own trained
commentator calls a moment beside the big model; then one tap switches to Kohli's last overs against
Pakistan in 2022 and the same commentator calls the cricket in an Indian voice.

## How it uses Mubit

- Every model call goes through Mubit's Anthropic endpoint (`claude-haiku-4-5`), one session per match.
  No model is called from the browser.
- Real traffic only: `scripts/replay_matches.py` replays distinct real matches of both sports, never
  padded or repeated calls. Held-out matches and the two demo matches are never replayed, so the
  trained model is judged on matches it never saw.
- Each line stores the Mubit request id of every call it made, and `GET /stats` counts calls from those
  ids.
- Producer fixes go back through Mubit in the same task and session.
- Mubit trains the adapted commentator; we compare it with the big model on held-out matches.

## Quality, cost and latency, side by side

| | Big model (`claude-haiku-4-5` via Mubit) | Our trained commentator |
|---|---|---|
| Agreement with the big model on held-out moments | baseline | to be measured |
| Cost per line | to be measured | to be measured |
| Tokens per line, in / out | 45,595 / 1,025 over 36 lines (about 1,267 / 28) | to be measured |
| First word, p50 / p95 | 524 ms / 789 ms | to be measured |
| Full line, p50 / p95 | 835 ms / 1,051 ms | to be measured |

Big-model figures: 36 lines on the staging service, read from `GET /stats` on 23 October 2026.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make smoke   # offline: replays one sample match per sport with a fake model, no keys needed
make check   # lint and the test suite, offline
make dev     # the server on localhost; set MUBIT_API_KEY in .env for real commentary
```

## Data

- Football: [StatsBomb open data](https://github.com/statsbomb/open-data), used under its licence.
- Cricket: ball-by-ball data from [Cricsheet](https://cricsheet.org).
- Video: each demo match's official highlights, embedded from the competition's YouTube channel and
  played muted; never downloaded or rehosted. The commentator reads the event feed, not the video.

## Architecture

These diagrams were drawn before the video redesign: where they say "stickman replay", the page now
plays the official highlights.

![C4 system context diagram: a fan watches and listens and a producer fixes lines in Touchline. Touchline reads events from StatsBomb and Cricsheet and sends every model call and every fix to Mubit, which passes calls on to the model provider.](docs/architecture/c4_context.png)

![C4 container diagram: the live match page (browser) gets events and lines from the match server by server-sent events and posts fixes to it. The traffic runner drives replays on the match server. The match server writes lines and fixes to the store, sends commentator calls and corrected lines to Mubit, and reads StatsBomb and Cricsheet.](docs/architecture/c4_container.png)

![C4 component diagram of the match server: the replayer feeds events to the moment filter, which passes key moments to the commentator agent. The agent calls tools for score, player facts and recent play, makes its model call through the Mubit client, saves the line to the store and pushes it to the live stream. The fix handler saves fixes and sends corrected lines through the Mubit client.](docs/architecture/c4_component.png)

## Pre-existing work

All application code was written during the event. The only files brought in are the team's own deploy
tooling (`Dockerfile`, `scripts/deploy.sh` and the bootstrap script), copied from our starter repo; that
commit names its source.

## What we'd build next

Today Touchline calls replays of real matches, with the commentary synced to the official footage.
Next:

- **More sports, then esports.** Any sport with real event data, through the same agent, tools and
  Mubit task; then esports and video-game events, where the match data already comes as a live feed.
- **Live streams, not just replays.** Calling a match as it is broadcast, with the same producer fixes
  feeding the same training loop.

## Team

- Atilade ([@atiladeokegab](https://github.com/atiladeokegab)): lead and design
- Persia ([@PersiaF04](https://github.com/PersiaF04)): full stack

How the team works, the rules for our AI agents and the build process: [TEAMWORK.md](TEAMWORK.md).
