# Touchline: every feature

The detail behind the [README](../README.md). Links to code are relative to the repo root.

## What Touchline is

**Touchline** describes a match aloud for fans who can't see it. It plays a match's broadcast
highlights, and as each key moment plays (a goal, a wicket, a three) it calls it in one short line,
read aloud in a commentator's voice and shown as a large subtitle. It describes key moments, not
every pass: what happened and who did it, often with the score. Football shots say where on the pitch they came
from, from the event data's own locations (#172). The page itself works by keyboard and screen
reader, with every control a 44 px target, checked by axe on the home and live pages
([`web/e2e/a11y.spec.ts`](../web/e2e/a11y.spec.ts), #170).

One agent calls every sport. It reads the match's real event data, looks up the score, the player and
recent play with tools, and never sees anything from later in the match than the moment it is
calling. A producer corrects any line that's wrong, and the fix goes back through Mubit beside the
line, as a correction for the commentator's next training.

## What each feature is

| Feature | Status | Proof in the code |
|---|---|---|
| [The seven matches](#the-seven-matches) | Live | [`GET /matches`](https://night-shift-5zvig7nbvq-ew.a.run.app/matches), [`agent/feed.py`](../agent/feed.py) |
| [Two commentators: lead and analyst](#two-commentators-lead-and-analyst) | Live (#130, #142) | [`core/insight.py`](../core/insight.py), [`core/replay.py`](../core/replay.py) |
| [Ask, by typing](#ask-by-typing-or-by-voice) | Live | [`POST /replays/{id}/ask`](../core/app.py), [`agent/ask.md`](../agent/ask.md) |
| [Ask, by voice](#ask-by-typing-or-by-voice) | Live (#145) | [`web/src/voice.ts`](../web/src/voice.ts), [`web/src/components/MicButton.tsx`](../web/src/components/MicButton.tsx), [`web/src/voice.test.ts`](../web/src/voice.test.ts) |
| [Follow a player: shot map](#follow-a-player) | Live | [`GET /replays/{id}/players/{name}/shots`](../core/app.py), [`web/src/components/ShotMap.tsx`](../web/src/components/ShotMap.tsx) |
| [Follow a player: picker and profile card](#follow-a-player) | Live (#140, #152) | [`GET /replays/{id}/players/{name}/profile`](../core/app.py), [`web/src/components/ProfileCard.tsx`](../web/src/components/ProfileCard.tsx) |
| [Producer fixes](#producer-fixes) | Live | [`POST /lines/{id}/fix`](../core/app.py), [`tests/test_core_fix.py`](../tests/test_core_fix.py) |
| [Big model vs ours](#big-model-vs-ours) | Live under the Proof card (#144, #147, #150) | [`data/side_by_side.json`](../data/side_by_side.json), [`eval/side_by_side.py`](../eval/side_by_side.py) |
| [The Proof panel](#the-proof-panel) | Live | [`GET /stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats), [`core/stats.py`](../core/stats.py) |
| Live screen layout: the video in a card, Lines and Proof beside it, playback controls | Live (#132) | [`web/src/components/Live.tsx`](../web/src/components/Live.tsx) |

### The seven matches

<img src="img/wall.png" alt="The home page in a dark theme, at 1440 wide. The amber Touchline. wordmark top left; on the right the links Matches (with a green dot, the current page), Replays, Review and About. Under the eyebrow Touchline: the describer that checks itself, the heading Every match deserves to be described, the line Most matches have no audio description. A blind or low-vision fan following one gets no description, a short paragraph on what it does and what a replay costs. Then nine tiles in three columns and three rows, each with a Jump to the big moment pill and the link Tap to hear it called. First the three long-tail matches: Orlando v North Carolina (NWSL · 24 May 2018) and Netherlands v Nepal (Women's T20 World Cup Qualifier · 22 Jan 2026), each marked No audio description that we could find and Whole match, every key moment, over a drawn stadium; then Brighton v Bristol City (Women's Super League · 21 Jan 2024), marked No described broadcast that we could find and Highlights, synced to video. Then the six famous ones, each over a broadcast still and marked Highlights, synced to video: Battle of the Bridge (Chelsea v Tottenham, 2016); Messi v Mbappé (2022 World Cup final); India v Pakistan (T20 World Cup, 2022); Kobe's 81 v Toronto (2006); Jordan's last shot as a Bull (1998 NBA Finals, Game 6); Verstappen, P17 to P1 (2024 São Paulo Grand Prix). Below them, the credits for the match data and the highlights." width="100%">

One match from the long tail and six famous ones, in four sports, each replayed from real event data
and called by the same commentator with the same prompt. Each plays over its broadcast highlights. A line is never shown or spoken before its moment reaches the picture: the YouTube player's clock gates it
([`web/src/gate.ts`](../web/src/gate.ts)).

| Match | Sport and data | What it calls |
|---|---|---|
| The long tail: Brighton 3-2 Bristol City, Women's Super League, 2024 | Football, StatsBomb | The five goals: Bristol City come level twice, then Terland's winner in stoppage time |
| The Battle of the Bridge: Chelsea 2-2 Tottenham, 2016 | Football, StatsBomb | The four goals, Hazard's equaliser that made Leicester champions |
| Argentina v France, 2022 World Cup final | Football, StatsBomb | Messi's two goals, Di María, Mbappé's three, the shoot-out |
| India v Pakistan, 2022 T20 World Cup | Cricket, Cricsheet | The wickets, the sixes, Kohli's two sixes off Rauf, the last ball |
| Michael Jordan's last shot as a Bull, 1998 NBA Finals Game 6 | Basketball, NBA play-by-play | The fourth quarter's baskets, Jordan's steal from Malone, the winning shot, the buzzer |
| Kobe Bryant's 81 against Toronto, 2006 | Basketball, NBA play-by-play | His baskets through the second half, the record-breaking points, the buzzer |
| Max Verstappen from 17th to win the 2024 São Paulo Grand Prix | F1, OpenF1 timing | The rain, the safety car, the red flag, Verstappen taking the lead, the flag |

The booth is two commentators: Jim, the lead, and Julian, the analyst, who call each other by name
([`core/voice.py`](../core/voice.py) `NAMES`). Lines are voiced by ElevenLabs `eleven_v3` with an audio tag per moment: shouting for a goal or a
wicket, hushed for the build-up ([`core/voice.py`](../core/voice.py), [docs/voice.md](voice.md)).

### Two commentators: lead and analyst

The lead calls each big moment. In the quiet stretches between them, an analyst fills the gap with a
stat line built only from the pre-match pack and the match so far, in a calmer second voice. The
two take turns until the next moment (#297): the analyst's stat, the lead coming back to it, then
the next stat, each line one that ends before the moment ([`core/insight.py`](../core/insight.py)
`Gaps.line`). Stat lines are stored and reused
by later replays of the same match.

Since #142 the analyst has its own prompt ([`agent/analyst.md`](../agent/analyst.md)) with the stat
as the event, and each fact states its period, such as "this season before tonight". Analyst lines
and the lead's replies run on `claude-sonnet-5-5` with its lowest thinking setting
(`between_tools`), unrecorded, so they never split the moment lines' Mubit task
([`agent/commentator.py`](../agent/commentator.py)).

### Ask, by typing or by voice

<img src="img/ask.png" alt="The live page during Kobe's 81. In the Lines card, an Ask entry: the question How many points does Kobe have so far? in italics, and the answer: Kobe Bryant has 41 points tonight! He just nailed that three from 26 feet to bring the Lakers within ten of Toronto." width="100%">

A viewer types a question mid-replay. The answer uses only what has happened up to the moment on
screen, so it never spoils what comes next. It is spoken by the analyst, at a gap in the commentary; the
question and answer take over the caption, and only a decisive moment cuts the answer off, which
then offers "Hear it again" ([`core/app.py`](../core/app.py) `ask`, [`agent/ask.md`](../agent/ask.md),
[`web/src/turns.ts`](../web/src/turns.ts), [`tests/test_core_ask.py`](../tests/test_core_ask.py)). Answers
go through Mubit unrecorded: they have their own prompt.

**Talk (#380):** the Talk button pauses the match and the speaking queue and opens a natural
conversation with the commentator (an ElevenLabs agent: its own turn-taking and interruptions). The
agent's custom LLM is [`core/converse.py`](../core/converse.py) `POST /converse/v1/chat/completions`,
which answers each turn through the same checked Ask path (Claude via Mubit, unrecorded), from the
match cut at the moment the talk began. When the fan goes quiet for 12 s, or presses Resume or Escape,
the match resumes where it paused. Where it can't start (no mic, no agent, off air) Ask is still there.
Setup, keyed, once: `ELEVENLABS_API_KEY=... CONVERSE_LLM_SECRET=<random> uv run python
scripts/converse_agent.py --url https://<service>/converse/v1`, then deploy with `CONVERSE_AGENT_ID`
and `CONVERSE_LLM_SECRET` set ([`tests/test_converse.py`](../tests/test_converse.py)).

**By voice (#145):** hold the mic button, or the space bar, and
speak; the browser's own speech recognition fills the box and sends it. The answer is held until the
current line ends and no big moment is due, then spoken
([`web/src/voice.ts`](../web/src/voice.ts), [`web/src/turns.ts`](../web/src/turns.ts), [`web/src/turns.test.ts`](../web/src/turns.test.ts)).
Where the browser has no speech recognition, the button is hidden and typing still works.

### Follow a player

<img src="img/shotmap.png" alt="The shot map sheet for Kobe Bryant: Before tonight 461 of 1036 (44%), Tonight 16 of 26. A half court with grey dots for his shots before tonight, green for made and red rings for missed tonight. Beside it, hit rate by zone: Mid-Range 211 of 490, 43%; Restricted Area 118 of 214, 55%; Above the Break 3 58 of 178, 33%; and the rest." width="100%">

Tap the chip for the player in the latest moment: their shots from the season before (from the
match's pre-match pack) and tonight's so far, with hit rate by zone. It reads only moments up to the
one on screen ([`core/app.py`](../core/app.py) `shots`, [`core/predict.py`](../core/predict.py),
[`tests/test_core_shots.py`](../tests/test_core_shots.py)).

Or follow anyone in the match: search for them in the Follow picker, and a profile card shows their
record before tonight and tonight's so far, while their lines are marked in the log. Like the shot
map, it reads only moments up to the one on screen ([`core/app.py`](../core/app.py) `players` and
`profile`, [`core/predict.py`](../core/predict.py),
[`web/src/components/FollowPicker.tsx`](../web/src/components/FollowPicker.tsx),
[`web/src/components/ProfileCard.tsx`](../web/src/components/ProfileCard.tsx),
[`tests/test_follow.py`](../tests/test_follow.py), [`web/src/follow.test.ts`](../web/src/follow.test.ts)).

<img src="img/follow.png" alt="The live page during Kobe's 81, LAK 65-75 RAP, 06:22, Q3, on the live site after #152. On the right, a profile card: Following Kobe Bryant, Los Angeles Lakers, with an Unfollow button; Before tonight 461 of 1036 (44%) in 38 games; Tonight 16 of 26 (62%); and a Shot map · Kobe Bryant chip. Below it, the Lines card with a bar reading Following Kobe Bryant · 2 lines and a Clear button. His two lines, Kobe Bryant from three, assisted by Devean George! at 06:22 and Kobe Bryant with the running jumper, 30 points for Bryant, Lakers trail 53 to 69. at 09:36, are edged in amber and tagged BRYANT; between them, the analyst's line, Before tonight he's made 461 of 1036 shots, 44 percent over 38 games, so thirty points here is a big night above his usual rate. Under the video, the caption marked LEAD repeats the three. The video area says Highlights can't play here, because the browser was headless." width="100%">

### Producer fixes

<img src="img/fix.png" alt="The Fix this line sheet over Kobe's 81. Touchline said: Kobe Bryant with the running jumper from ten feet, he's got thirty points, but Toronto still leads fifty-three to sixty-nine. The producer's corrected line: Running jumper, Kobe Bryant! That is 30 for him, but the Lakers still trail by sixteen, 53 to 69. Then chips for what was wrong, with Tone picked (Wrong fact, Wrong player, Wrong score, Tone, Other), Send fix and Cancel, and the note: Your fix goes back through Mubit and is kept beside the original." width="100%">

A producer corrects a wrong line on the page. The server stores the fix beside the original and sends
it back through the same Mubit task and session, as a second turn: that is how a correction is built to become
training signal; `/stats` counts them (`fixes_recorded`). No adapter version trained on them is recorded
yet ([`core/app.py`](../core/app.py) `fix_line`, [`tests/test_core_fix.py`](../tests/test_core_fix.py)).

### Big model vs ours

The big model's line on six held-out moments (three football, three cricket, matches never used for
training), recorded through Mubit with recording off, with each line's latency and cost
([`data/side_by_side.json`](../data/side_by_side.json), [`eval/side_by_side.py`](../eval/side_by_side.py),
[`tests/test_side_by_side.py`](../tests/test_side_by_side.py)). Until an adapter version passes Mubit's test,
those lines stand as the baseline ours must match, and the panel says why there is no line of ours:
Mubit serves an adapter only once a version passes, and only in its console's Try models, never to
the app by API. The panel
([`web/src/components/SideBySide.tsx`](../web/src/components/SideBySide.tsx)) sits under the Proof card on
every live page.

### The Proof panel

The screenshot that stood here (24 Oct, 16:04 UTC) showed a fix threshold and an adapter "Training" that the card no longer shows (#281), so it is removed; the live page shows the current card.

Calls checked, this match and all matches (#204); cost per full replay; live latency, cost per line and lines
called, split by lead and analyst (#166); the fixes that passed the check, recorded in Mubit as training data, and
how many have been heard since; Line check's row and its held-out result (#298, #317); and Score check's version,
examples and held-out score, with the earlier commentary tasks folded away (#321, #363). All from `GET /stats`
(its `by_speaker` for the split); the console reading under Earlier tasks is dated and read by hand, never live ([`web/src/components/ProofPanel.tsx`](../web/src/components/ProofPanel.tsx),
[`core/stats.py`](../core/stats.py)).

## The product: where this goes

> **Vision, not what's built.** This weekend's build is the seven replays above. This is the full product.

- **Every streamed match, described aloud.** Leagues, clubs, rights holders and streaming platforms
  switch it on for the long tail of matches they stream with no describer, in any language or voice:
  lower-league and grassroots football, the women's game, club and county cricket.
- **A describer per broadcaster, owned by them.** Each broadcaster gets its own cheap commentator as
  a Mubit adapter, trained on its own matches, and each producer correction that passes the
  number check is recorded as training data for it.
- **Built for fans who can't see the screen.** Audio first, with keyboard and screen reader working
  throughout (#170, built). Football shots already say where on the pitch they came from, from the
  event data's own locations (#172).
- **The fan layer.** Ask by typing or voice, a choice of voices, and Follow a player, on any match.
- **At scale,** Redis fans each match's lines out to every viewer and caches them across instances,
  and SurrealDB, already the graph behind Follow a player, takes over every pack
  ([docs/ARCHITECTURE.md](ARCHITECTURE.md#at-scale-a-plan-not-built)).
