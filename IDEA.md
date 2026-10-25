# The idea

The full, current requirements are in `docs/PRD.md` (PRD v6). Build and review against it.

The lead writes this once the team has agreed the idea, and no issue is created before it is
complete. If your task doesn't fit this page, open a change-request (AGENTS.md §7).

## Problem

Most matches are played with nobody describing them for a fan who can't see the screen. Sky
describes about 109 of the Premier League's 380 games a season; outside those, live audio description
is voluntary and patchy, run club by club at the ground, and at Wrexham the fans and local sponsors
raised £4,000 for it themselves (sources: `docs/evidence.md`, The problem). A blind or low-vision fan
following a stream of a match nobody describes gets the crowd and a bare ticker.

## The idea

Touchline is the describer that checks itself: it describes matches aloud for blind and low-vision
fans, for the matches a platform streams with nobody describing them, in any sport with an event feed. Switch from a football match to a
cricket match and the same agent changes its context on the fly and calls the new sport. It watches the
feed, looks up the facts it needs with tools (score, player, recent play) and calls each key moment in
one short spoken line, with the model's first word in about half a second (median, `GET /stats`),
over a replay of iconic real moments. It checks the numbers in each moment's line before it speaks. A producer fixes any line that's wrong, and the fix is sent back
through Mubit as a training example. Every call goes through Mubit: this is training, not serving.
Each prompt change started a new Mubit task: the console shows 8 tasks,
7 adapters and 0 serving, the best commentary task at 58.3% against a 95% target; none has passed,
and the app calls no adapter.

## What we build

- Match replayer: plays real event feeds in real time or sped up: football from StatsBomb open data
  (e.g. the 2022 World Cup final), cricket ball by ball from Cricsheet.
- Sport switch: pick another sport or moment mid-demo; the screen and the commentator follow.
- Commentator agent: one generalist with one fixed system prompt and 2-4 tools, so every call in every
  sport is one Mubit task; the sport goes in the message. One line per key moment (shots, goals, cards,
  wickets, boundaries), not every pass or dot ball.
- Live match page: the match's broadcast highlights (embedded YouTube, muted; a re-upload where the official one won't embed) play as the stage; as each
  key moment plays, its line shows as a large subtitle and is spoken in an emotional commentator voice
  (a setting: Indian voice for cricket, British for football by default), with the score.
- Producer fix: edit or reject a line on the page; the corrected line goes back through Mubit and is
  kept with the original.
- Real traffic: replay many matches tonight so the task passes 25 kept examples with varied, real calls.
- Proof panel: per-line latency and cost, how many lines were fixed, and the adapter's test result.
- Side by side (planned, not built): the big model and our trained commentator calling the same
  moment, in Mubit's Try models, once a version passes Mubit's test; the app can't call an adapter.

- Iconic extra screens, after the core works: Messi v Mbappé (2022 World Cup final), the Battle of the Bridge (Chelsea 2-2 Tottenham, 2016), Kobe Bryant's 81 points (2006), Michael Jordan's last shot (1998 NBA Finals), Max Verstappen from 17th to win at São Paulo 2024. Same commentator, same prompt.

## What we don't build

- Video or vision input to the model: the commentator reads event data; the highlights video is display only.
- A live real-world match feed: replays of real matches only.
- A system prompt per sport, or more than one commentator persona: either splits the Mubit task.
- Sports beyond football, cricket, basketball and F1 this weekend, and any sport without real event data.
- Unsourced statistics in the pitch.
- Our own fine-tuning or model hosting: Mubit trains the model.
- Any claim that our model beats the big one, or matches it: no adapter has passed Mubit's 95% target yet.
- Betting or betting odds. Predictions are in scope (the lead, 2026-10-24) only as rates from each player's pre-match record plus the match so far, never from a later moment.

## The demo, in one line

Brighton v Bristol City plays and Touchline calls each moment aloud, with the Proof card beside it; a
wrong line is caught before air and auto-fixed (Denise O'Sullivan, 39:39, Orlando v North Carolina); a
producer fixes Terland's 30:57 line to "the Seagulls" and the next lines on that match carry the fix
(94:48: "Brighton take the lead, 3-2!" becomes "The Seagulls go three-two up";
`scripts/fix_then_later.py`); the fix goes to Score check training (Cahill, examples 2,161 → 2,163);
Mubit's console shows it as training, not serving; and it ends on the buyer, the streaming platforms
that carry the WSL and NWSL, at about $0.45 a replay with the voice included.

## Areas and owners

Each person owns their area's directories outright (AGENTS.md §6). The core is the shared
contracts; only the lead changes it.

| Area | Directories | Owner | Issues |
|---|---|---|---|
| backend: core, commentator, data, eval, deploy | `core/`, `agent/`, `data/`, `eval/`, `scripts/`, `docs/`, `Makefile`, `pyproject.toml`, `Dockerfile`, `.dockerignore` | @atiladeokegab [Zeus], @atiladeokegab, @atiladeokegab [Hermes] | #1, #3, #13, #14, #15, #16, #17, #20, #25, #40 |
| web | `web/` | @PersiaF04 | #4, #18, #19 |
| tests | `tests/`, `data/sample/` | @atiladeokegab [Prometheus] | #6, #11, #12 |
| submission | `README.md`, `docs/` | @atiladeokegab [Zeus] | #1, #21 |

Deploy owner: @atiladeokegab. Only they run `make deploy`, from `main` after it moves; two
laptops deploying undo each other.

### Ceilings

The shortcuts each area takes on purpose, and what replaces each if we outgrow it. Review checks
work against these; a shortcut not listed here is a finding.

- core: one server process and a JSON-lines store of lines and fixes; a database if two producers edit at once.
- commentator: replayed matches only, from StatsBomb, Cricsheet, the NBA's play-by-play and OpenF1; a live data provider's feed if this goes beyond the demo.
- voice: ElevenLabs `eleven_v3` (docs/voice.md), browser speech only as the fallback; the last 500 lines' audio kept in one process's memory; a bucket if Cloud Run runs more than one instance.
- data and eval: matches chosen by hand; a sampler across all 80 competition-seasons if the adapter needs more variety.
