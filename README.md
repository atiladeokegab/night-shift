<div align="center">

<img src="docs/banner.svg" alt="Banner: the word Touchline. in amber over a drawn night stadium with floodlights and a green pitch, the tagline A live AI commentator for matches nobody calls, and a red ON AIR pill." width="100%">

<br>

[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-live%20stream-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Mubit](https://img.shields.io/badge/Mubit-training%20the%20commentator-FFB547)](https://mubit.ai)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-commentator%20voice-000000?logo=elevenlabs&logoColor=white)](https://elevenlabs.io)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-live-4285F4?logo=googlecloud&logoColor=white)](https://night-shift-5zvig7nbvq-ew.a.run.app)

**A live AI commentator for every match nobody calls. A big model calls each moment through Mubit, which is training a smaller commentator on those calls (6 adapter versions so far, none passed yet), with every producer fix kept as a correction.**

[**Try it live**](https://night-shift-5zvig7nbvq-ew.a.run.app) · [**For judges**](#for-judges) · [**Real numbers**](#real-numbers) · [**Architecture**](docs/ARCHITECTURE.md) · [**Known limitations**](#known-limitations) · [**Run it**](#run-it) · [**Demo script**](docs/demo.md)

<img src="docs/img/live.png" alt="The live page (old layout) calling Kobe Bryant's 81-point game. Top left, the score bar reads LAK 65-75 RAP, 06:22, Q3, REPLAY, and an ON AIR pill names the voice, Sam. The large subtitle reads: Kobe Bryant from 26 feet, three! Lakers down ten, 65 to 75, but Bryant's got 41 already. Under it, a dock with Wall, the four sports, Voice and Next match. On the right, the Lines card with an Ask box, a Shot map chip for Kobe Bryant and each line with a Fix button and its model first-text-word time, and the Proof card with first text word p50 0.53 s and p95 0.74 s, $0.0018 a line, the lines count, 0 fixes, and the adapter as not trained yet (captured before 13:04 UTC)." width="100%">

<sub>The live site on 24 October 2026, captured in headless Chrome: Kobe Bryant's 81 against Toronto
being called. YouTube won't play in a headless browser, so the video area is empty and the page says
so; the lines, voice timing and numbers are live.</sub>

</div>

---

Built at Night Shift: Mubit Hackathon, London, 23 to 25 October 2026. Track: Own your intelligence layer.

## For judges

**Live:** <https://night-shift-5zvig7nbvq-ew.a.run.app> (Cloud Run, real Mubit calls, sound on).

### The 60-second path

1. Open the live link and tap **Kobe's 81 v Toronto**. The first line is called and spoken within
   about 20 seconds, timed to the moment in the broadcast.
2. In the **Lines** card, type a question into **Ask the commentator**, for example "How many points
   does Kobe have?". The answer is spoken and lands in the log.
3. Tap the **Shot map · Kobe Bryant** chip: every shot before tonight, tonight's made and missed, and
   his hit rate by zone.
4. Tap **Fix** on any line: a producer corrects it, and the fix goes back through Mubit beside the
   original.
5. Read the **Proof** card, then check it: `curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/stats`.
6. Tap **Cricket** in the sport bar: the same commentator, same prompt, calls India v Pakistan.

### What each feature is

| Feature | Status | Proof in the code |
|---|---|---|
| [The six matches](#the-six-matches) | Live | [`GET /matches`](https://night-shift-5zvig7nbvq-ew.a.run.app/matches), [`agent/feed.py`](agent/feed.py) |
| [Two commentators: lead and analyst](#two-commentators-lead-and-analyst) | Live; analyst lines saying the stat itself in progress (#142) | [`core/insight.py`](core/insight.py), [`core/replay.py`](core/replay.py) |
| [Ask, by typing](#ask-by-typing-or-by-voice) | Live | [`POST /replays/{id}/ask`](core/app.py), [`agent/ask.md`](agent/ask.md) |
| [Ask, by voice](#ask-by-typing-or-by-voice) | Live (#145) | [`web/src/voice.ts`](web/src/voice.ts), [`web/src/components/MicButton.tsx`](web/src/components/MicButton.tsx), [`web/src/voice.test.ts`](web/src/voice.test.ts) |
| [Follow a player: shot map](#follow-a-player) | Live | [`GET /replays/{id}/players/{name}/shots`](core/app.py), [`web/src/components/ShotMap.tsx`](web/src/components/ShotMap.tsx) |
| [Follow a player: picker and profile card](#follow-a-player) | In progress (#140) | |
| [Producer fixes](#producer-fixes) | Live | [`POST /lines/{id}/fix`](core/app.py), [`tests/test_core_fix.py`](tests/test_core_fix.py) |
| [Big model vs ours](#big-model-vs-ours) | Recorded and merged (#144, #147); the panel isn't on any page until its hook-up lands after #146 | [`data/side_by_side.json`](data/side_by_side.json), [`eval/side_by_side.py`](eval/side_by_side.py) |
| [The Proof panel](#the-proof-panel) | Live | [`GET /stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats), [`core/stats.py`](core/stats.py) |
| Live screen layout: the video in a card, Lines and Proof beside it, playback controls | Live (#132) | [`web/src/components/Live.tsx`](web/src/components/Live.tsx) |

#### The six matches

<img src="docs/img/wall.png" alt="The home page: the line A live AI commentator for matches nobody calls above the heading Pick a match, then tiles for Battle of the Bridge (Chelsea 2-2 Tottenham, 2016), Messi v Mbappé (the 2022 World Cup final) and India v Pakistan (T20 World Cup 2022), each with its sport, result, voice and a Start replay button; below them the tops of Kobe's 81 v Toronto, Jordan's last shot and Verstappen, P17 to P1." width="100%">

Six famous matches in four sports, each replayed from real event data over its broadcast highlights
and called by the same commentator with the same prompt. A line is never shown or spoken before its
moment reaches the picture: the YouTube player's clock gates it ([`web/src/gate.ts`](web/src/gate.ts)).

| Match | Sport and data | Voice | What it calls |
|---|---|---|---|
| The Battle of the Bridge: Chelsea 2-2 Tottenham, 2016 | Football, StatsBomb | British Football Announcer | The four goals, Hazard's equaliser that made Leicester champions |
| Argentina v France, 2022 World Cup final | Football, StatsBomb | British Football Announcer | Messi's two goals, Di María, Mbappé's three, the shoot-out |
| India v Pakistan, 2022 T20 World Cup | Cricket, Cricsheet | Raju | The wickets, the sixes, Kohli's two sixes off Rauf, the last ball |
| Michael Jordan's last shot, 1998 NBA Finals Game 6 | Basketball, NBA play-by-play | Sam | The fourth quarter's baskets, Jordan's steal from Malone, the winning shot, the buzzer |
| Kobe Bryant's 81 against Toronto, 2006 | Basketball, NBA play-by-play | Sam | His baskets through the second half, the record-breaking points, the buzzer |
| Max Verstappen from 17th to win the 2024 São Paulo Grand Prix | F1, OpenF1 timing | British Football Announcer | The rain, the safety car, the red flag, Verstappen taking the lead, the flag |

Lines are voiced by ElevenLabs `eleven_v3` with an audio tag per moment: shouting for a goal or a
wicket, hushed for the build-up ([`core/voice.py`](core/voice.py), [docs/voice.md](docs/voice.md)).

#### Two commentators: lead and analyst

The lead calls each big moment. In the quiet stretches between them, an analyst fills the gap with a
stat line built only from the pre-match pack and the match so far, in a calmer second voice; every
fourth line, the lead replies ([`core/insight.py`](core/insight.py)). Stat lines are stored and reused
by later replays of the same match.

**In progress (#142):** on the live site the analyst often repeats the play instead of saying the
number. #142 gives the analyst its own prompt with the stat as the event, kept unrecorded so it never
splits the commentator's Mubit task.

#### Ask, by typing or by voice

<img src="docs/img/ask.png" alt="The live page during Kobe's 81. In the Lines card, an Ask entry: the question How many points does Kobe have so far? in italics, and the answer: Kobe Bryant has 41 points tonight! He just nailed that three from 26 feet to bring the Lakers within ten of Toronto." width="100%">

A viewer types a question mid-replay. The answer uses only what has happened up to the moment on
screen, so it never spoils what comes next. It is spoken by the analyst, at a gap in the commentary; the
question and answer take over the caption, and nothing cuts the answer off ([`core/app.py`](core/app.py) `ask`, [`agent/ask.md`](agent/ask.md),
[`web/src/turns.ts`](web/src/turns.ts), [`tests/test_core_ask.py`](tests/test_core_ask.py)). Answers
go through Mubit unrecorded: they have their own prompt.

**By voice (#145):** hold the mic button, or the space bar, and
speak; the browser's own speech recognition fills the box and sends it. The answer is held until the
current line ends and no big moment is due, then spoken
([`web/src/voice.ts`](web/src/voice.ts), [`web/src/turns.ts`](web/src/turns.ts), [`web/src/turns.test.ts`](web/src/turns.test.ts)).
Where the browser has no speech recognition, the button is hidden and typing still works.

#### Follow a player

<img src="docs/img/shotmap.png" alt="The shot map sheet for Kobe Bryant: Before tonight 461 of 1036 (44%), Tonight 16 of 26. A half court with grey dots for his shots before tonight, green for made and red rings for missed tonight. Beside it, hit rate by zone: Mid-Range 211 of 490, 43%; Restricted Area 118 of 214, 55%; Above the Break 3 58 of 178, 33%; and the rest." width="100%">

Tap the chip for the player in the latest moment: their shots from the season before (from the
match's pre-match pack) and tonight's so far, with hit rate by zone. It reads only moments up to the
one on screen ([`core/app.py`](core/app.py) `shots`, [`core/predict.py`](core/predict.py),
[`tests/test_core_shots.py`](tests/test_core_shots.py)).

**In progress (#140):** a Follow picker for anyone in the match, their lines highlighted in the log,
and a profile card with their record coming in and tonight's line.

#### Producer fixes

<img src="docs/img/fix.png" alt="The Fix this line sheet over Kobe's 81. Touchline said: Kobe Bryant with the running jumper from ten feet, he's got thirty points, but Toronto still leads fifty-three to sixty-nine. The producer's corrected line: Running jumper, Kobe Bryant! That is 30 for him, but the Lakers still trail by sixteen, 53 to 69. Then chips for what was wrong, with Tone picked (Wrong fact, Wrong player, Wrong score, Tone, Other), Send fix and Cancel, and the note: Your fix goes back through Mubit and is kept beside the original." width="100%">

A producer corrects a wrong line on the page. The server stores the fix beside the original and sends
it back through the same Mubit task and session, as a second turn: that is how a correction is built to become
training signal. No fix has been made on the live site yet, so no fix has trained a model ([`core/app.py`](core/app.py) `fix_line`, [`tests/test_core_fix.py`](tests/test_core_fix.py)).

#### Big model vs ours

The big model's line on six held-out moments (three football, three cricket, matches never used for
training), recorded through Mubit with recording off, with each line's latency and cost
([`data/side_by_side.json`](data/side_by_side.json), [`eval/side_by_side.py`](eval/side_by_side.py),
[`tests/test_side_by_side.py`](tests/test_side_by_side.py)). Until an adapter version passes Mubit's test,
those lines stand as the baseline ours must match, and the panel says why there is no line of ours:
Mubit serves an adapter only once a version passes, and only in its console's Try models, never to
the app by API. The panel that shows it
([`web/src/components/SideBySide.tsx`](web/src/components/SideBySide.tsx)) is merged but isn't shown on
any page until its hook-up lands after #146.

#### The Proof panel

<img src="docs/img/proof.png" alt="The Proof card: model first text word p50 0.53 s and p95 0.78 s, cost per line $0.0018, the lines count and 0 fixes; the adapter: Training, Mubit is building the adapter; adapter cost not measurable, because Mubit doesn't report it to the app; and a note on what first text word measures." width="50%">

Live latency, cost per line, lines called, fixes and the adapter's state, computed from the store and
the same numbers as `GET /stats` ([`web/src/components/ProofPanel.tsx`](web/src/components/ProofPanel.tsx),
[`core/stats.py`](core/stats.py)).

### Against the judging criteria

Each criterion weighs the same; one line each, with where to check it.

- **Use of Mubit (a correction becomes a model update):** every call goes through one Mubit task; its recorded lines have trained [6 adapter versions](#real-numbers) so far (none passed yet), and a producer's [fix](#producer-fixes) is stored beside the line as the correction for the next version.
- **Usefulness (a real recurring task):** most matches every weekend have no commentator; Touchline calls [six real matches in four sports](#the-six-matches) from their real event data.
- **Technical execution:** a line in [0.53 s to its first word](#real-numbers) (p50), gated on the video's clock, an offline test suite (`make check`) and a live smoke test on every deploy; [architecture](docs/ARCHITECTURE.md) and [known limitations](#known-limitations).
- **Demo:** two minutes on the live URL, scripted in [docs/demo.md](docs/demo.md); the [60-second path](#the-60-second-path) above is the short version.

## The product: where this goes

> **Vision, not what's built.** This weekend's build is the six replays above. This is the full product.

- **Any live match, any sport.** A commentator in any language or voice, for the leagues, clubs and
  broadcasters with no commentary budget: lower-league and grassroots football, the women's game,
  club and county cricket.
- **A trained commentator per broadcaster, owned by them.** Each broadcaster gets its own cheap
  commentator as a Mubit adapter, trained on its own matches, and every producer correction is a
  training signal that makes it better.
- **The fan-facing layer.** Ask by typing or voice, a choice of voices, and Follow a player, on any match.
- **At scale,** Redis fans each match's lines out to every viewer and caches them across instances,
  and SurrealDB holds players, teams, matches and seasons as a graph
  ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#at-scale-a-plan-not-built)).

## Real numbers

Read from the live service's [`GET /stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats) on
24 October 2026 at 13:04 UTC, adapter status included. They move as people use the site.

| | Big model (`claude-haiku-4-5` via Mubit) | Our trained commentator (Mubit adapter) |
|---|---|---|
| Lines called | 4,715 (4,836 Mubit calls, counted by their request ids) | none: not callable by the app |
| First word of the model's text, p50 / p95 | 534 ms / 779 ms | not measured |
| Full line, p50 / p95 | 881 ms / 1,131 ms | not measured |
| Cost per line | $0.0018 | not reported by Mubit |
| Tokens per line, in / out | about 1,648 / 29 (7,770,852 / 135,975 over 4,715 lines) | not measured |
| Producer fixes | 0 so far; the first is made in the demo | |

"First word" is from the moment to the first word of the model's text reply, not the audio:
speech synthesis and playback come after it.

**The adapter, exactly as it stands.** Mubit has trained 6 adapter versions on our task's recorded lines. All 6 are "not
ready": none has passed Mubit's test yet, and the best scored 55.8% on Mubit's test. That is the record in [`data/side_by_side.json`](data/side_by_side.json), copied by hand from
Mubit's console on 24 October 2026. We make no claim that the adapter matches the big model until a
result shows it. `/stats` reports the adapter's status as `training` (at 13:04 UTC), recorded from
the console with [`eval/record_adapter.py`](eval/record_adapter.py); it reports no agreement result,
because no version has passed.

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
shown as a large subtitle.

One agent calls every sport. It reads the match's real event feed, looks up the score, the player and
recent play with tools, and never sees anything from later in the match than the moment it is
calling. A producer corrects any line that's wrong, and the fix goes back through Mubit beside the
line, as a correction for the commentator's next training.

## How it uses Mubit

Every LLM call goes through Mubit, and Mubit trains a small commentator model on our recorded traffic;
producer fixes go into the same task as corrections. That smaller model is what would make a commentator for every match affordable.

1. **Every call goes through Mubit.** Each line is one call to Mubit's Anthropic endpoint
   (`claude-haiku-4-5`), or two when the agent uses its one permitted round of tools. There is one
   session per match, and no model is called from the browser
   ([`agent/commentator.py`](agent/commentator.py)).
2. **One task for every sport.** The system prompt, message template, tools and model are the same,
   byte for byte, for football, cricket, basketball and F1; the sport goes in the message. Mubit sees
   one task to learn from ([`agent/prompt.md`](agent/prompt.md), [`agent/tools.json`](agent/tools.json)).
3. **Real traffic only.** [`scripts/replay_matches.py`](scripts/replay_matches.py) replays distinct
   real football and cricket matches, never padded or repeated calls. Held-out matches and the demo
   matches are never replayed, so the trained model is judged only on matches it never saw.
4. **The demo key trains nothing.** The live site runs on a teammate's lent Mubit key with recording
   off (`MUBIT_RECORD=off` in [`scripts/deploy.sh`](scripts/deploy.sh)); training traffic comes from
   the replay script on the owner's key. If the lent key runs out, the commentator moves to the
   owner's key, which records. Ask answers and side-by-side runs are always unrecorded.
5. **A producer's fix is built as training signal.** A fix is stored beside the original line and
   sent back through the same Mubit task and session. No fix has been made on the live site yet
   (`fixes` is 0 in `/stats`), so the adapters so far were trained on recorded commentary only.
6. **Counted at Mubit.** Each line stores the Mubit request id of every call it made, and
   `GET /stats` counts calls from those ids.
7. **The trained model is measured, not assumed.** 6 adapters so far, none ready, best 55.8% on Mubit's test
   ([Real numbers](#real-numbers)). The aim is that it matches the big model at lower cost; we make
   no claim that it beats it.

## Architecture

The full picture, with a C4 container diagram of what runs now and a second, plan-only diagram for
scale: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Now.** One Cloud Run service: a FastAPI match server ([`core/`](core)) that also serves the React
page ([`web/`](web)). It replays a match's event feed, asks the commentator agent
([`agent/`](agent)) for each line through Mubit, has ElevenLabs voice it, keeps lines and fixes as
JSON lines on Cloud Storage, and streams moments and lines to the browser over server-sent events.
The commentator's tools and the shot map read per-match stats packs ([`data/packs/`](data/packs)).

**At scale (a plan, not built).**

- **Redis** as a shared cache of lines, stat lines and voice clips across instances (today each
  replay pays for its own lines, and voice clips sit in one instance's memory); pub/sub fan-out of
  each match's lines to thousands of viewers; per-viewer Ask limits.
- **SurrealDB** for players, teams, matches and seasons as a graph, behind the commentator's tools,
  Follow a player and the heat maps, replacing per-match JSON packs at thousands of matches.
- **What stays:** Mubit for every model call and the trained adapter, and Cloud Run as the host.

## Known limitations

- **The adapter isn't ready or callable.** 6 adapters, none ready, best 55.8% on Mubit's test. Mubit
  serves an adapter only in its console, so the app can't call one, and its cost per line isn't
  measurable.
- **One instance.** The service runs with `--max-instances 1` ([`scripts/deploy.sh`](scripts/deploy.sh)):
  replays and voice clips live in that process's memory
  ([`core/replay.py`](core/replay.py), [`core/voice.py`](core/voice.py)).
- **Every viewer starts their own replay.** Two people watching the same match pay Mubit twice for
  the big moments ([`core/replay.py`](core/replay.py)).
- **The store rewrites a whole object on every append**, and `/stats` reads the whole lines file each
  time, which is published after every line ([`core/store.py`](core/store.py), [`core/stats.py`](core/stats.py)).
  Fine for a demo; a database once two producers edit at once.
- **Cricket has no ball timestamps** in Cricsheet, so a ball counts as 30 seconds
  ([`core/replay.py`](core/replay.py)).
- **Line timing assumes the video starts with the replay**; the page doesn't send its player's clock
  back to the server ([`core/replay.py`](core/replay.py)).
- **Predictions are approximations:** the packs mark no starters, and a cricket batter's runs tonight
  include extras ([`core/predict.py`](core/predict.py)).
- **The highlights are re-uploads** for four of six matches, because the official uploads block
  embedding or don't exist. If one is taken down, the commentary carries on without the picture.
- **Not covered by tests:** the browser's speech playback ([`web/src/useSpeech.ts`](web/src/useSpeech.ts))
  and the live page's components as rendered; they are checked by hand and by screenshots. Real Mubit
  and ElevenLabs calls are checked only by the smoke test after each deploy.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make smoke   # offline: replays every sample match with a fake model, no keys needed
make check   # lint and the test suite, offline
make dev     # the server on localhost; set MUBIT_API_KEY in .env for real commentary
```

## Data and video

- Football: [StatsBomb open data](https://github.com/statsbomb/open-data), used under its licence.
- Cricket: ball-by-ball data from [Cricsheet](https://cricsheet.org).
- Basketball: stats.nba.com play-by-play, via the [shufinskiy/nba_data](https://github.com/shufinskiy/nba_data) mirror (Apache-2.0).
- F1: timing data from the [OpenF1](https://openf1.org) API.
- Video: broadcast highlights on YouTube, embedded and muted, never downloaded or rehosted; the
  commentator reads the event feed, not the video. The two basketball games are from the NBA's own
  channel. Argentina v France, Chelsea v Tottenham, India v Pakistan and the São Paulo Grand Prix are
  re-uploads or fan edits of the TV coverage by others, because the official uploads block embedding
  or don't exist.

## Pre-existing work

All application code was written during the event. The only files brought in are the team's own deploy
tooling (`Dockerfile`, `scripts/deploy.sh` and the bootstrap script), copied from our starter repo; that
commit names its source.

## What we'd build next

- **Scale**, as in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): Redis and SurrealDB, so one call per
  moment serves every viewer.
- **More sports, then esports.** Any sport with real event data, through the same agent, tools and
  Mubit task; then esports and video-game events, where the match data already comes as a live feed.
- **Live streams, not just replays.** Calling a match as it is broadcast, with the same producer fixes
  feeding the same training loop.

## Team

- Atilade ([@atiladeokegab](https://github.com/atiladeokegab)): lead and design
- Persia ([@PersiaF04](https://github.com/PersiaF04)): full stack

Requirements: [docs/PRD.md](docs/PRD.md); each one has an ID such as A-6.4 and a test. How the team
works, the rules for our AI agents and the build process: [TEAMWORK.md](TEAMWORK.md).
