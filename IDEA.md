# The idea

The lead writes this once the team has agreed the idea, and no issue is created before it is
complete. If your task doesn't fit this page, open a change-request (AGENTS.md §7).

## Problem

Most matches in most sports are played with nobody calling them: grassroots and lower-league football,
most of the women's game, club and county cricket. Fans following a stream or a live score get silence or
a bare ticker. A clever model could commentate them, but it is too slow to call a moment while it is
still on screen, and too expensive to run for every moment of every match.

## The idea

Touchline is one live AI commentator for any sport with an event feed. Switch from a football match to a
cricket match and the same agent changes its context on the fly and calls the new sport. It watches the
feed, looks up the facts it needs with tools (score, player, recent play) and calls each key moment in
one short spoken line, in under a second, over a replay of iconic real moments. A producer fixes any line that's wrong, and the fix is sent back
through Mubit, so the commentator is trained on corrected calls. Every call goes through Mubit, which
trains a small commentator model that gives the same calls as the big one: the cost that makes
commentary for every match possible.

## What we build

- Match replayer: plays real event feeds in real time or sped up: football from StatsBomb open data
  (e.g. the 2022 World Cup final), cricket ball by ball from Cricsheet.
- Sport switch: pick another sport or moment mid-demo; the screen and the commentator follow.
- Commentator agent: one generalist with one fixed system prompt and 2-4 tools, so every call in every
  sport is one Mubit task; the sport goes in the message. One line per key moment (shots, goals, cards,
  wickets, boundaries), not every pass or dot ball.
- Live match page: a stickman replay on the pitch or field for each sport, score, subtitles, and the
  line read aloud.
- Producer fix: edit or reject a line on the page; the corrected line goes back through Mubit and is
  kept with the original.
- Real traffic: replay many matches tonight so the task passes 25 kept examples with varied, real calls.
- Proof panel: per-line latency and cost, how many lines were fixed, and the adapter's test result.
- Side by side: the big model and our trained commentator calling the same moment (Mubit's Try
  models, unless Mubit lets the app call the adapter).

## What we don't build

- Video or vision input: the feed is event data, not pictures.
- A live real-world match feed: replays of real matches only.
- A system prompt per sport, or more than one commentator persona: either splits the Mubit task.
- Sports beyond football and cricket this weekend, and any sport without real event data.
- Unsourced statistics in the pitch.
- Our own fine-tuning or model hosting: Mubit trains the model.
- Any claim that our model beats the big one: it matches it, at lower cost.
- Betting, odds or predictions.

## The demo, in one line

The 2023 Women's World Cup final replays as stickmen and Touchline calls it aloud in under a second, the
producer fixes one wrong line on stage, our own trained commentator calls a moment beside the big model,
then one tap switches to Kohli's last overs against Pakistan in 2022 and the same commentator calls cricket.

## Areas and owners

Each person owns their area's directories outright (AGENTS.md §6). The core is the shared
contracts; only the lead changes it.

| Area | Directories | Owner | Issues |
|---|---|---|---|
| backend: core, commentator, data, eval, deploy | `core/`, `agent/`, `data/`, `eval/`, `scripts/`, `docs/`, `Makefile`, `pyproject.toml`, `Dockerfile`, `.dockerignore` | @atiladeokegab [Zeus], @atiladeokegab, @atiladeokegab [Hermes] | #1, #3, #13, #14, #15, #16, #17, #20, #25 |
| web | `web/` | @PersiaF04 | #4, #18, #19 |
| tests | `tests/`, `data/sample/` | @atiladeokegab [Prometheus], @atiladeokegab | #6, #11, #12 |
| submission | `README.md`, `docs/` | @atiladeokegab [Zeus] | #1, #21 |

Deploy owner: @atiladeokegab (Zeus). Only they run `make deploy`, from `main` after it moves; two
laptops deploying undo each other.

### Ceilings

The shortcuts each area takes on purpose, and what replaces each if we outgrow it. Review checks
work against these; a shortcut not listed here is a finding.

- core: one server process and a JSON-lines store of lines and fixes; a database if two producers edit at once.
- commentator: replayed StatsBomb and Cricsheet matches only; a live data provider's feed if this goes beyond the demo.
- web: browser speech for the voice; a hosted voice model if the browser voice sounds too flat on stage.
- data and eval: matches chosen by hand; a sampler across all 80 competition-seasons if the adapter needs more variety.
