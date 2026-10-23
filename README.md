<div align="center">

<img src="docs/banner.svg" alt="Banner: the word Touchline. in amber over a drawn night stadium with floodlights and a green pitch, the tagline A live AI commentator for matches nobody calls, and a red ON AIR pill." width="100%">

<br>

[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-live%20stream-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Mubit](https://img.shields.io/badge/Mubit-trains%20the%20commentator-FFB547)](https://mubit.ai)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-commentator%20voice-000000?logo=elevenlabs&logoColor=white)](https://elevenlabs.io)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-live-4285F4?logo=googlecloud&logoColor=white)](https://night-shift-5zvig7nbvq-ew.a.run.app)

**A live AI commentator for every match nobody calls, trained through Mubit on its own calls and every producer fix.**

[**Try it live**](https://night-shift-5zvig7nbvq-ew.a.run.app) · [**The six screens**](#the-six-screens) · [**How it uses Mubit**](#how-it-uses-mubit) · [**For judges**](#for-judges) · [**Run it**](#run-it) · [**Demo script**](docs/demo.md)

<img src="docs/img/live.png" alt="The live page, from the design mockup. A drawn night stadium stands in for the highlights video. Top left, the score bar reads ESP 1-0 ENG, 28:29, 1st half, REPLAY. Top right, a red ON AIR pill names the British commentator. In the lower third, the moment tag 28:29 GOAL sits above the large subtitle: Olga Carmona! Low across Earps and in! Spain lead the World Cup final! Under it, a dock with Fixtures, a Football and Cricket switch and Voice: British, and a video timeline with a small Synced to video label. On the right, a Lines card lists each line with its clock, its first-word time and a Fix button, and a Proof card shows first word p50 and p95, cost per line, lines, fixes and the adapter's result." width="100%">

<sub>The live page as designed (<code>docs/mockup/index.html</code>). In the product the broadcast
highlights play where the drawn stadium is; the numbers in this picture are samples, not measurements.</sub>

</div>

---

Built at Night Shift: Mubit Hackathon, London, 23 to 25 October 2026. Track: Own your intelligence layer.

## The problem

Somewhere tonight a county cricket chase goes to the last ball, and nobody calls it. A women's
league side scores the goal of its season, and the stream is silent. Most matches in most sports are
played like this: grassroots and lower-league football, most of the women's game, club and county
cricket. Fans following a stream or a live score get a bare ticker, or nothing.

A big model could commentate them. But it is too slow to call a moment while the moment is still on
screen, and too expensive to run for every moment of every match.

## What Touchline is

**Touchline** gives every match a commentator. It plays a match's broadcast highlights, and as each
key moment plays it calls it in one short, emotional line, read aloud in a commentator's voice and
shown as a large subtitle. A line is never shown or spoken before its moment reaches the picture.

One agent calls every sport. It reads the match's real event feed, looks up the score, the player and
recent play with tools, and never sees anything from later in the match than the moment it is
calling. A producer fixes any line that's wrong in one tap, and the fix goes back through Mubit to
train the commentator.

## How it uses Mubit

Every LLM call goes through Mubit, and Mubit trains a small commentator model on our traffic and on
producer fixes. That smaller model is what would make a commentator for every match affordable.

1. **Every call goes through Mubit.** Each line is one call to Mubit's Anthropic endpoint
   (`claude-haiku-4-5`), with one session per match. No model is called from the browser.
2. **One task for every sport.** The system prompt, message template, tools and model are the same,
   byte for byte, for football, cricket, basketball and F1; the sport goes in the message. Mubit sees
   one task to learn from.
3. **Real traffic only.** `scripts/replay_matches.py` replays distinct real football and cricket
   matches, never padded or repeated calls. Held-out matches and the demo matches are never replayed,
   so the trained model is judged only on matches it never saw.
4. **A producer's fix is training signal.** A fix is stored beside the original line and sent back
   through the same Mubit task and session.
5. **Counted at Mubit.** Each line stores the Mubit request id of every call it made, and
   `GET /stats` counts calls from those ids.
6. **The trained model is measured, not assumed.** We compare Mubit's trained commentator with the
   big model on held-out moments. That result is **in progress**: the adapter has not finished
   training. The aim is that it matches the big model at lower cost; we make no claim that it beats it.

## The six screens

Six famous matches, each replayed from real event data over its broadcast highlights and called by
the same commentator with the same prompt.

| Screen | Sport and data | Voice | What it calls |
|---|---|---|---|
| Spain v England, 2023 Women's World Cup final | Football, StatsBomb | British | Carmona's winner, Earps's penalty save, the chances at both ends |
| Argentina v France, 2022 World Cup final | Football, StatsBomb | British | Messi's two goals, Di María, Mbappé's three, the shoot-out |
| India v Pakistan, 2022 T20 World Cup | Cricket, Cricsheet | Indian | The wickets, the sixes, Kohli's two sixes off Rauf, the last ball |
| Michael Jordan's last shot, 1998 NBA Finals Game 6 | Basketball, NBA play-by-play | American play-by-play | The fourth quarter's baskets, Jordan's steal from Malone, the winning shot, the buzzer |
| Kobe Bryant's 81 against Toronto, 2006 | Basketball, NBA play-by-play | American play-by-play | His baskets through the second half, the record-breaking points, the buzzer |
| Lewis Hamilton's 2024 British Grand Prix win | F1, OpenF1 timing | British announcer | Overtakes and lead changes, pit stops, the rain, the last lap, the flag |

The voice is a setting on the page, and a change applies from the next line. Lines are voiced by
ElevenLabs `eleven_v3` with an audio tag per moment: shouting for a goal or a wicket, hushed for the
build-up ([docs/voice.md](docs/voice.md)). The browser's own speech is the fallback.

## For judges

Live URL: <https://night-shift-5zvig7nbvq-ew.a.run.app> (Cloud Run, real Mubit calls).
Every number below was read from that service's `GET /stats` on 23 October 2026 at 23:25 UTC; anything
not yet measured says so.

| Criterion | Evidence | Measured | Check it |
|---|---|---|---|
| Use of Mubit | Every call goes through Mubit's Anthropic endpoint, one session per match, one task for every sport | 189 lines; 198 Mubit calls, counted by their request ids | `curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/stats` (`mubit_requests`) |
| Use of Mubit: a correction becomes a model update | `POST /lines/{line_id}/fix` stores the fix beside the original and sends it through the same task and session | 0 fixes on the live service so far; the first is made in the demo | `fixes` in `/stats` |
| Usefulness | Real matches from real event data in four sports, called the way a TV commentator would | 6 demo matches served | `curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/matches` |
| Technical execution | FastAPI server, durable store on Cloud Storage, server-sent event stream, commentary gated on the video player's clock, an offline test suite and a live smoke test on every deploy | Health: ok | `curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/health` |
| Demo | A 3-minute live demo on the deployed URL, scripted in [docs/demo.md](docs/demo.md) | To be recorded | |
| Track: quality, cost and latency side by side | The proof panel and `GET /stats` show latency, cost per line, lines, fixes and the trained model's result | Big model, 189 lines: first word p50 529 ms, p95 984 ms; full line p50 821 ms, p95 1,332 ms; $0.0015 a line. The trained model's agreement: in progress | `curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/stats` |

### Quality, cost and latency, side by side

| | Big model (`claude-haiku-4-5` via Mubit) | Our trained commentator |
|---|---|---|
| Agreement with the big model on held-out moments | baseline | in progress |
| Cost per line | $0.0015 | in progress |
| Tokens per line, in / out | about 1,408 / 26 (266,051 / 4,846 over 189 lines) | in progress |
| First word, p50 / p95 | 529 ms / 984 ms | in progress |
| Full line, p50 / p95 | 821 ms / 1,332 ms | in progress |

### Status

As of 23 October 2026, 23:30 UTC.

| Capability | Status |
|---|---|
| The six screens, replayed from real data and synced to the broadcast highlights (A-6.4, A-10) | Live |
| One task for every sport; facts from tools, never from later in the match (A-1.2, A-1.4, A-10.3) | Live |
| Expressive voice per sport, with a voice setting (A-6.3, A-6.6) | Live |
| Proof panel: latency, cost per line, lines, fixes and the adapter's result (A-7.1) | Live |
| Producer fix: the server stores it and sends it through Mubit (A-4.1) | Live; the page's Fix button is merged and goes live with the next deploy |
| The home page as a wall of all six matches playing at once (A-6.5) | In progress |
| Mubit's trained commentator against the big model on held-out moments (R-8) | In progress |

## Run it

Needs [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make smoke   # offline: replays every sample match with a fake model, no keys needed
make check   # lint and the test suite, offline
make dev     # the server on localhost; set MUBIT_API_KEY in .env for real commentary
```

Or open the live URL: <https://night-shift-5zvig7nbvq-ew.a.run.app>.

## Architecture

- **Match server** (`core/`, FastAPI on Cloud Run): replays a match's event feed, streams moments and
  lines to the page over server-sent events, takes producer fixes and serves `GET /stats`.
- **Moment picker** (`agent/feed.py`): turns StatsBomb, Cricsheet, NBA and OpenF1 data into key
  moments, never reading ahead of the moment it emits.
- **Commentator agent** (`agent/`): one fixed prompt and its tools; one call through Mubit per line.
- **Store**: lines and fixes as JSON lines on Cloud Storage; on Cloud Run the server refuses to start
  without it.
- **Live page** (`web/`): the YouTube highlights player drives the clock; each line is shown and
  spoken when the picture reaches its moment.

C4 diagrams: [context](docs/architecture/c4_context.png), [containers](docs/architecture/c4_container.png),
[components](docs/architecture/c4_component.png). They were drawn before the video redesign: where they
say "stickman replay", the page now plays the broadcast highlights.

## Data and video

- Football: [StatsBomb open data](https://github.com/statsbomb/open-data), used under its licence.
- Cricket: ball-by-ball data from [Cricsheet](https://cricsheet.org).
- Basketball: stats.nba.com play-by-play, via the [shufinskiy/nba_data](https://github.com/shufinskiy/nba_data) mirror (Apache-2.0).
- F1: timing data from the [OpenF1](https://openf1.org) API.
- Video: broadcast highlights on YouTube, embedded and muted, never downloaded or rehosted; the
  commentator reads the event feed, not the video. Argentina v France is from FIFA's own channel, the
  two basketball games from the NBA's and Silverstone from Formula 1's. The Women's World Cup final
  (ITV's coverage) and India v Pakistan (the TV feed) are re-uploads by others: no FIFA, ICC or
  broadcaster upload of those highlights exists.

## Pre-existing work

All application code was written during the event. The only files brought in are the team's own deploy
tooling (`Dockerfile`, `scripts/deploy.sh` and the bootstrap script), copied from our starter repo; that
commit names its source.

## What we'd build next

Today Touchline calls replays of real matches, with the commentary synced to the broadcast footage.
Next:

- **More sports, then esports.** Any sport with real event data, through the same agent, tools and
  Mubit task; then esports and video-game events, where the match data already comes as a live feed.
- **Live streams, not just replays.** Calling a match as it is broadcast, with the same producer fixes
  feeding the same training loop.

## Team

- Atilade ([@atiladeokegab](https://github.com/atiladeokegab)): lead and design
- Persia ([@PersiaF04](https://github.com/PersiaF04)): full stack

Requirements: [docs/PRD.md](docs/PRD.md); each one has an ID such as A-6.4 and a test. How the team
works, the rules for our AI agents and the build process: [TEAMWORK.md](TEAMWORK.md).
