<div align="center">

<img src="docs/banner.svg" alt="Banner: the word Touchline. in amber over a drawn night stadium with floodlights and a green pitch, the tagline The describer that checks itself, and a red ON AIR pill." width="100%">

<sub><b>Touchline: the describer that checks itself.</b> For the match nobody described.</sub>

<br>

[![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-live%20stream-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Mubit](https://img.shields.io/badge/Mubit-training%20the%20commentator-FFB547)](https://mubit.ai)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-commentator%20voice-000000?logo=elevenlabs&logoColor=white)](https://elevenlabs.io)
[![Cloud Run](https://img.shields.io/badge/Cloud%20Run-live-4285F4?logo=googlecloud&logoColor=white)](https://night-shift-5zvig7nbvq-ew.a.run.app)

# Touchline: the describer that checks itself

**Touchline describes matches aloud for fans who can't see them, and checks the score and the key
numbers in each line against the match data before it goes on air.**

<img src="docs/media/demo.gif" alt="A 9-second screen recording of the live Touchline page: lines are called one after another and stack in the Lines card as the match goes on, and one of them carries an auto-fixed tag." width="100%">

<sub>Touchline calls match moments as spoken lines. Each line is checked against the match data, and one is marked auto-fixed.</sub>

[**Try it live**](https://night-shift-5zvig7nbvq-ew.a.run.app) · [**On stage**](#on-stage) · [**What's new**](#whats-new-tonight) · [**How well the check works**](#how-well-the-check-works) · [**Every feature**](docs/features.md) · [**The evidence**](docs/evidence.md) · [**Architecture**](docs/ARCHITECTURE.md)

</div>

What you hear are **replays, as if live**: real matches' event data played back over their
broadcast highlights, each line called at its moment, in four sports.

## On stage

1. **The grader catches a wrong line before air.** Every lead line goes through a number check
   first: the score, who leads, the margin, the players' counts. In Jordan's last game as a Bull the
   model wrote "Chicago Bulls take the lead, 85-86!" when Utah led 86-85. The check's reason was
   "Chicago Bulls do not lead". That line was never said: a line built from the data went out instead
   ("Michael Jordan with the driving layup. Utah Jazz lead eighty-six, eighty-five.") and the wrong
   one went to the producer's fix queue. A failed line gets one retry before the data line is used
   ([`core/insight.py`](core/insight.py) `wrong_numbers`).
2. **A producer's fix becomes Score check training data.** When a producer fixes a line for a wrong
   score, player or fact, the line as first said goes to Mubit as one recorded example for Score check, a separate task whose
   answer comes from code, never a model ([`agent/scorecheck.py`](agent/scorecheck.py) `teach`,
   [`eval/linecheck.py`](eval/linecheck.py) `gold`). This is **training, not serving**: no
   trained version answers anything on the site yet.
3. **Close your eyes.** Press **E**: the picture goes black, only the line and the score stay, and
   the commentary carries on. That is the match as a blind or low-vision fan follows it.

## Who pays

A club's or a league's media team, for described highlights of every match, every week. Nobody has
agreed to pay yet and we have not set a price. What we know is our cost: **about $0.35 per
key-moments replay, voice included** ($0.12 model, $0.23 voice, over 78 replays on the live
[`GET /stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats), 24 October 2026 at 21:34 UTC).
That is a highlights replay, not a whole 90 minutes. Why it matters: [the problem](docs/evidence.md#the-problem).

## For judges

**Live:** <https://night-shift-5zvig7nbvq-ew.a.run.app> (Cloud Run, real Mubit calls, sound on).
Built at Night Shift: Mubit Hackathon, London, 23 to 25 October 2026. Track: Own your intelligence layer.

### The 60-second path

1. Tap **Brighton v Bristol City**, a Women's Super League match from the long tail, and press
   **E** to close your eyes.
2. Tap **Kobe's 81 v Toronto** and ask the commentator "How many points does Kobe have?", or press
   **Talk** and ask out loud.
3. Tap **Fix** on any line: a producer corrects it, and the fix goes back through Mubit.
4. Read the **Proof** card, then check it: `curl -s https://night-shift-5zvig7nbvq-ew.a.run.app/stats`.

### What's new tonight

- **A graph of teams and players:** SurrealDB holds 612 football matches and everyone in them, and answers only from matches before this one, so nothing later leaks.
- **Talk:** press **Talk** and the match pauses while you speak with the commentator; each answer goes through Claude via Mubit and the same check as Ask. Escape, or 12 s of silence, resumes.
- **One speaking queue:** no line cuts another off mid-word; a big moment goes first, and routine lines that have gone stale are dropped.
- **Teams tab:** press **T** for each side's form, their last meetings and the squad, as they stood before the match.
- **One broadcast pair:** both voices share one tone per moment, lit up for a big moment and calm for a routine one, and in quiet stretches they take turns on one player.

Everything else, with its code and tests: [every feature](docs/features.md).

## Mubit: training, not serving

Every model call goes through Mubit, which records the traffic as training data. Mubit's console,
read by hand on 24 October 2026 at about 19:15 UTC ([`data/mubit_console.json`](data/mubit_console.json)),
shows 8 tasks, 7 adapters and 0 serving: the best commentary task scores 58.3% against a 95% target.
No adapter has passed, the app cannot call one, and we make no claim that any matches the big model.
Score check, the narrower task above, has 2,161 examples sent to training, 60 of them from producer
fixes (46 the model already matched, 5 corrected, 9 not corrected), backfilled at 21:35 UTC; the big
model agreed with the code's answer key on 74 of 74 held-out lines (`/stats` `scorecheck`).

Ask is checked the same way: on a keyed run of 33 questions (`eval.ask_eval --provider mubit`,
recording off), 32 answers were right, 1 wrong and 0 refused. The wrong one, "What just happened?"
at Lakers 120-102, had an invented lead change; the check caught it and the safe answer was said.

The console, the correction loop and a real fix step by step:
[the evidence](docs/evidence.md).

## How well the check works

Two sets of 300 lines the live site had said, labelled right or wrong by a separate model before the
checker ran on them. The rules were written against the first set, so its score is tuned-on; the
held-out set is the honest measure. This table is generated from
[`eval/checker_eval.py`](eval/checker_eval.py) by [`eval/readme_numbers.py`](eval/readme_numbers.py),
and [`tests/test_readme_numbers.py`](tests/test_readme_numbers.py) fails if it drifts.

<!-- checker-eval:start -->
| Set | Checker | Lines | Wrong (labels) | Caught | False alarms |
|---|---|---|---|---|---|
| Held-out, every line | Number check (rules) | 300 | 6 | 2 of 6 | 0 |
| Held-out, lead lines | Number check (rules) | 288 | 5 | 2 of 5 | 0 |
| Held-out, lead lines | Line check (keyed run) | 288 | 5 | 3 of 5 | 3 |
| First set (rules tuned on it) | Number check (rules) | 300 | 15 | 14 of 15 | 0 |
<!-- checker-eval:end -->

The number check runs before a line is said; Line check is a second model that reads each lead line
after it is said. Lead lines leave out the analyst's. The Line check row is a keyed run,
read from [`eval/linecheck_heldout.json`](eval/linecheck_heldout.json), which `/stats` serves as
`linecheck.heldout`. A Line check flag only sends a line to the producer's queue; it never stops it
being said. These are small counts: one more catch moves held-out recall by about 17 points. How the
lines were picked and labelled, and what the check still misses: [the evidence](docs/evidence.md#how-well-the-check-works).

## Known limitations

- **The checks miss most wrong lines they were not tuned on** (the table above). They check the
  score, the leader and the key numbers, not every claim.
- **The voice comes seconds after the moment.** The text's first word is out in about half a second;
  the audio clip takes longer (`audio_first_ms_p50` on `/stats`).
- **No adapter serves.** Mubit serves one only in its console, once a version passes its test.
- **A fix is locked only where `PRODUCER_TOKEN` is set**; a fix that contradicts the data gets a 422
  either way and never reaches Mubit ([`core/app.py`](core/app.py) `fix_line`).
- **One instance, and every viewer starts their own replay** ([`scripts/deploy.sh`](scripts/deploy.sh),
  [`core/replay.py`](core/replay.py)).
- **Cricket has no ball timestamps** in Cricsheet, so a ball counts as 30 seconds.
- **The highlights are re-uploads** for four of the seven matches with video; if one is taken down,
  the commentary carries on without the picture.
- **Two files break the repo's 1,000-line rule** ([AGENTS.md](AGENTS.md)): `core/insight.py` and
  `tests/test_core_voice.py`. Splitting them waits until after the event.

## Run it

Needs [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make smoke   # offline: lint, the test suite, and every sample match replayed with a fake model
make check   # lint and the test suite, offline
make dev     # the server on localhost; export MUBIT_API_KEY for real commentary (make dev doesn't read .env)
```

`make dev` records to Mubit unless `MUBIT_RECORD=off` is exported; the deploy sets it off. The web
tests are `cd web && npm ci && npm test`. CI runs the smoke and the browser tests on every PR into
`integration`, and every deploy runs a live smoke on the real URL.

The live site's budget guard; `0` turns one off.

| Setting | Default | What it limits |
|---|---|---|
| `MAX_LIVE_REPLAYS` | 4 | Replays making new lines at once; past it, stored lines play in browser speech |
| `REPLAYS_PER_HOUR` | 10 | Replay starts per visitor per hour; then 429 |
| `ASKS_PER_HOUR` | 20 | Asks per visitor per hour; then 429 |
| `DAILY_BUDGET_USD` | 50 | Today's model and voice spend (UTC); past it, stored lines only and Ask is off air |

## Data and video

- Football: [StatsBomb open data](https://github.com/statsbomb/open-data), used under its licence.
- Cricket: ball-by-ball data from [Cricsheet](https://cricsheet.org).
- Basketball: stats.nba.com play-by-play, via the [shufinskiy/nba_data](https://github.com/shufinskiy/nba_data) mirror (Apache-2.0).
- F1: timing data from the [OpenF1](https://openf1.org) API.
- Video: broadcast highlights on YouTube, embedded and muted, never downloaded or rehosted; the
  commentator reads the event feed, not the video. The two basketball games are from the NBA's own
  channel, and Brighton v Bristol City from Brighton & Hove Albion's. Argentina v France, Chelsea v
  Tottenham, India v Pakistan and the São Paulo Grand Prix are re-uploads or fan edits of the TV
  coverage by others, because the official uploads block embedding or don't exist.

## Pre-existing work

All application code was written during the event. The only files brought in are the team's own deploy
tooling (`Dockerfile`, `scripts/deploy.sh` and the bootstrap script), copied from our starter repo; that
commit names its source.

## What we'd build next

- **Scale**, as in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): Redis and SurrealDB, so one call per
  moment serves every viewer.
- **More sports, then esports**, through the same agent, tools and Mubit task.
- **Live streams, not just replays**, with the same producer fixes feeding the same training loop.

The longer view: [where this goes](docs/features.md#the-product-where-this-goes).

## Team

- Atilade ([@atiladeokegab](https://github.com/atiladeokegab)): lead and design
- Persia ([@PersiaF04](https://github.com/PersiaF04)): full stack

Requirements: [docs/PRD.md](docs/PRD.md); each one has an ID such as A-6.4, and the tests that
check one name its ID. How the team works: [TEAMWORK.md](TEAMWORK.md).
