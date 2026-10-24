# Touchline: the evidence

The detail behind the [README](../README.md): the correction loop, how Touchline uses Mubit, how the check was measured, and the problem it answers.

## Correction loop, with evidence

Every moment line goes through a number check before it is spoken: the score, who leads, the
margin, the players' counts and, in football, what kind of event it was ([`core/insight.py`](../core/insight.py)).
A line that fails is tried once more. If the retry passes, the failed try is sent to Mubit as an
automatic correction attempt, with no person involved; if it fails too, a line built from the match
data is spoken instead. A producer fixes the rest from the page, and each fix goes to Mubit the same
way. Only a fix whose corrected reply passes the number check is recorded as training data; one that
fails is stored but not recorded (`recorded: false`), and a fix to an analyst's stat line is never
recorded. A fix that passes that first, unrecorded check is then sent again, the same request, on
the recording key; that recorded second reply is checked again and can still fail. It stays
recorded in Mubit (`recorded: true`, `reply_passed: false`), but it doesn't count toward the next
version (`fixes_toward_next`).
A correction is the next turn of the line's own call, so only the messages change, never the
prompt, tools or model. It says what was wrong and gives the facts, and the commentator writes
the fixed line itself. A correction is recorded only after an unrecorded try passes the number
check. If the recorded reply still fails, it is marked and does not count toward the next version.
The turn the code builds for the Jordan fix in the table below, had it been made after #245
(Jazz v Bulls, 1998 NBA Finals Game 6, moment 30), sent after the wrong line:

```text
Producer correction: Wrong score
The facts at this moment. Score: Utah Jazz 86, Chicago Bulls 85. Leader: Utah Jazz lead 86-85. Player total: Michael Jordan, 43 points tonight.
The producer's line: Michael Jordan with the driving layup, forty-three for him! Utah still lead, eighty-six to eighty-five.
Say your line again, corrected: the line alone, at most 20 words.
```

Each fix stores this turn as `correction`, with `reply_passed`.

A fix applies to the next lines straight away, and Mubit records it for training. Every line the
commentator writes later in that match, in this replay and the next, carries its last five fixes in the user
message: when, what the commentator said, what was wrong and the producer's line. The system
prompt, tools and model stay the same, so it is still one Mubit task, and the number check still
runs on every line.

The analyst's stat lines, the lead's replies to them and Ask answers get the same number check,
against the stat and the match so far: a wrong number is tried once more, then the line is dropped
and never said (an answer becomes the off-air line).

**Mubit, exactly as its console shows it.** Mubit's console overview, read on 24 October 2026 at
about 19:15 UTC, shows 8 tasks, 7 adapters and 0 serving. Mubit keys a task on its fingerprint: the
system prompt, the tools, the output format and the model. Each prompt change started a new task, so
our recorded commentary is split across six separate tasks rather than one. The overview lists these
six, as they are; the other 2 tasks, Line check among them, aren't listed on it. None has passed
Mubit's 95% target and no adapter serves.

| Task | Status | Examples | Quality |
|---|---|---|---|
| Live television commentator 5 (current) | Collecting examples | 269 | 14.3% |
| Live sports commentator | Testing | 155 | 5.9% |
| Live sports commentator 2 | Testing | 141 | 58.3% |
| Live television commentator 3 | Testing | 132 | 55.8% |
| Live television commentator | Collecting examples | 118 | 0.0% |
| Live television commentator 2 | Testing | 111 | 25.0% |

What we did about it: [Line check](#how-it-uses-mubit), one frozen task whose answer key comes from
code, with its recorded checks and the producers' fixes. Beside the rules (#298), it checks each new lead
line; stored replays are checked once as they play (its count is `linecheck` on [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)). Its
flags go to the producer's fix queue ([how well it works](#line-check-beside-the-rules)).
[`data/side_by_side.json`](../data/side_by_side.json) and `/stats`'s `earlier_tasks.adapter.console`
carry this same read ([`data/mubit_console.json`](../data/mubit_console.json)); a test fails if they
or the README disagree with it ([`tests/test_readme_numbers.py`](../tests/test_readme_numbers.py)).

The corrections waiting and how the check left the lead's calls are on the live
[`GET /stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats): `fixes_recorded`,
`fixes_toward_next`, `fixes_auto_sent`, `autonomy` and `autonomy_by_match`. They move as people use
the site, so they are not copied here.

**Why a correction is a follow-up turn.** Mubit has no feedback API: it learns from the calls it
records. So a correction is sent, on purpose, as the next turn of the wrong line's own call, in the
same task and session: the original request, the line the model said, then the correction turn
above (the reason, the facts, the producer's line). Mubit records the commentator's corrected
reply, so it is training data for the next version ([`agent/commentator.py`](../agent/commentator.py)
`correct`, [`tests/test_core_fix.py`](../tests/test_core_fix.py)).

**What a correction teaches, and its limit.** The recorded example holds the moment's own request,
a wrong call, what was wrong with it and the right call, written by the model itself. Fixes made
before #245 asked for the producer's line word for word instead. We can't yet say what a version
trained on either learns: no version trained on corrections has been tested.

**Anatomy of a fix.** One real correction from the review queue to Mubit. The fix stores the
correction call's Mubit request id and the exact correction turn, and `GET /lines/{line_id}`
returns them under `fix`.

Read 24 Oct 2026 from one real fix (Bulls v Jazz 1998, the Jordan layup).

| Step | Value |
|---|---|
| The wrong line | The model said "Jordan with the driving layup! Chicago Bulls take the lead, 85-86!" Utah led 86-85. The number check caught it before air: a safe line built from the data was spoken instead ("Michael Jordan with the driving layup. Utah Jazz lead eighty-six, eighty-five."), and the line went to the fix queue |
| The checker's reason | "Chicago Bulls do not lead" |
| The producer's fix | "Michael Jordan with the driving layup, forty-three for him! Utah still lead, eighty-six to eighty-five." (reason: Wrong score) |
| What Mubit was given (`fix.correction`, #245) | Not in this fix: it predates #245 |
| The commentator's corrected reply, and whether it passed the number check (`fix.reply_passed`) | Not in this fix: it predates #245 |
| Mubit request id | `mreq_01a16eb90c9076f0b88abe5089b47e1e` |
| Recorded for training | Yes: `recorded: true` |
| What the next replay said | At 16:23:09 UTC, five seconds after the fix, the producer's line, marked fixed, with no model call (line `3ccce616bff14206bd6b3c8126343b88`) |

---

## How it uses Mubit

Every LLM call goes through Mubit, which records our traffic as training data for a small commentator
model; producer fixes go into the same task as corrections. A version is used only once it passes
Mubit's test, and none has yet ([as its console shows it](#correction-loop-with-evidence)). That smaller model is what would make a commentator for every match affordable.

1. **Every call goes through Mubit.** Each moment line is one call to Mubit's Anthropic endpoint
   (`claude-haiku-4-5`, recorded), or two when the agent uses its one permitted round of tools. The
   analyst's stat lines and the lead's replies are one call each to `claude-sonnet-5-5`, unrecorded. There is one
   session per match, and no model is called from the browser
   ([`agent/commentator.py`](../agent/commentator.py)).
2. **One task for every sport.** The system prompt, message template, tools and model are the same,
   byte for byte, for football, cricket, basketball and F1; the sport goes in the message. Mubit sees
   one task to learn from ([`agent/prompt.md`](../agent/prompt.md), [`agent/tools.json`](../agent/tools.json)).
3. **Real traffic only.** [`scripts/replay_matches.py`](../scripts/replay_matches.py) replays distinct
   real football and cricket matches, never padded or repeated calls. Held-out matches and the demo
   matches are never replayed, so the trained model is judged only on matches it never saw.
4. **The demo key trains nothing.** The live site runs on a separate demo Mubit key with recording
   off (`MUBIT_RECORD=off` in [`scripts/deploy.sh`](../scripts/deploy.sh)); training traffic comes from
   the replay script on the owner's key. If the demo key runs out, the commentator moves to the
   owner's key, which records. Ask answers and side-by-side runs are always unrecorded.
5. **A producer's fix that passes the number check is recorded to Mubit for training.** A fix is
   stored beside the original line. Its corrected reply is checked first, unrecorded; only one that
   passes is sent as the next turn of that line's request on the owner's key (`MUBIT_FALLBACK_KEY`)
   with recording on, whatever `MUBIT_RECORD` says. One that fails is stored with `recorded: false`,
   and a fix to an analyst's stat line stays unrecorded, like those lines. The Proof card shows the fixes recorded and how many count toward the next
   adapter (`fixes_toward_next` on `/stats`). No adapter version trained on them is recorded yet.
6. **Mubit request ids we stored.** Each line stores the Mubit request id of every call it made,
   and `GET /stats` counts calls from those ids; nothing checks them against Mubit's console.
7. **The trained model is measured, not assumed.** Each prompt change started a new task: 7
   adapters, best 58.3% against a 95% target, 0 serving, and the app does not
   call an adapter ([the console read](#correction-loop-with-evidence)). The
   aim is that one matches the big model at lower cost; we make no claim that any does.
8. **Line check, a task with exact answers.** A separate, frozen recorded task checks a stored line against
   its moment's facts and answers one JSON object: score, leader, player total and event, each
   `ok`, `wrong` or `not_said` ([`eval/linecheck.py`](../eval/linecheck.py),
   [`eval/seed_linecheck.py`](../eval/seed_linecheck.py)). The answer key comes from code, never a
   model, and a line code can't decide is left out. Some examples are **planted**: a right line with
   one field changed so it is wrong, marked `planted: true`. They balance the labels; they are not
   real errors the commentator made. Every line of the WSL match (3913122) and the F1 race (9636)
   is held out and never sent to Mubit. Beside the rules (#298), it checks each new lead line; stored
   replays are checked once as they play (`linecheck` on [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)). A flag sends the
   line to the producer's fix queue and never stops it being said
   ([how well it works](#line-check-beside-the-rules)).

## How well the check works

Before a lead line is spoken, the number check reads it against the moment's data
([`core/insight.py`](../core/insight.py) `wrong_numbers`, which includes the event check). We measured
it twice, on two separate sets of 300 lines the live site had already said.

**On lines it was never tuned on, it catches little.** The numbers are the table in the
[README](../README.md#how-well-the-check-works), generated from
[`eval/checker_eval.py`](../eval/checker_eval.py) by [`eval/readme_numbers.py`](../eval/readme_numbers.py),
so they are not repeated here. The first set is the one the rules were written against, so its score
is a tuned-on score, not the result.

With 6 wrong held-out lines, one more catch or miss moves held-out recall by about 17 points.

**A note on cricket streaks.** A rule for cricket streaks ("back-to-back sixes") was built and then
dropped. On the held-out set it flagged two lines that the labeller called right:
- "Kohli makes it four in a row!" at 17.6. Kohli's fours before it came at 17.1 and 17.3. After the
  four at 17.3 he kept the strike, so 17.4 was his, and 17.4 and 17.5 together made only 2 runs.
- "back-to-back maximums for Hardik" at 11.6. Pandya's six before it came at 11.1. After it he kept
  the strike, so 11.2 was his, and 11.2 and 11.3 together made 1 run.

By the ball numbers neither streak happened, so the labels may be wrong. We did not change them, and
the precision on unseen lines must not drop, so the rule is out. It is the first set's one miss.

**Two sets, and why.** The first set's 7 misses showed six kinds of wrong line the check did not
test: a basketball clock said to the second, a streak ("back-to-back sixes"), a batter's runs over a
span of balls, blocked vs off target vs saved, the shootout's score vs the match score, and a level
claim on a football moment that is not a goal. We added a general rule for each one (#293), except
the cricket streak (above), and tested each rule on lines of our own as well, right lines included:
a time in minutes and seconds, the shot clock, a negated or wished-for streak, "not wide", and
"were level" or "level with the last defender". Fixing a set's own misses makes its score look better
than the check really is, so we drew a second, held-out set and labelled it before the new rules
ran on it.

**How the lines were picked.** Both sets come from read-only copies of the live store's lines. Each
set keeps every distinct line once, by match, moment and text. Fallback lines are left out, because
they are built from the data. Each set is stratified by match: 30 lines from each match, or all of
them when a match has fewer, and the rest by each match's share, with a fixed seed.
- First set: seed 219, from a copy taken on 24 October 2026 at about 15:40 UTC (6,446 records). It
  has lead lines only, 13 of them replies. Only 6 of its lines had been through the live check when
  they were said.
- Held-out set: seed 293, from a copy taken on 24 October 2026 at about 18:17 UTC (7,170 records).
  It excludes all 300 lines of the first set and includes the analyst's lines (47 of them). 90 of
  its lines had already passed the live check when they were said, so its wrong lines are the ones
  that check let through.

**Who labelled them.** Each set was labelled by a separate, fresh agent, before the check was run on
it. Both agents were models, not people. Each agent read every line with:
- the match header;
- the moment's data;
- the eight moments before it;
- for a reply, what the analyst had just said;
- for the analyst, what the analyst was given.

Neither agent had access to the checker. Both labelled each line right or wrong by the same written
rules in [`eval/checker_eval.py`](../eval/checker_eval.py) (`RULES`). A line is wrong if it has:
- a number the data contradicts or does not give;
- a wrong player or team;
- a wrong lead or level claim;
- a wrong event;
- leaked reasoning.

Leaving something out is never wrong. Each set's labels were committed before the checker was run
on it ([`eval/checker_labels.jsonl`](../eval/checker_labels.jsonl),
[`eval/heldout_labels.jsonl`](../eval/heldout_labels.jsonl)).

**What it still misses.** The 4 held-out lines labelled wrong that it let through are of kinds it
does not test:
- an analyst line calling a two-pointer a three, with the wrong points total;
- "at the halfway mark" with 12 of 20 overs bowled;
- "one kick away" after the shootout's winning kick;
- "Kohli! Two sixes tonight". The labeller saw only this six in the eight moments it was shown. The
  match data has an earlier Kohli six at 11.4, so we think this label is mistaken too.

**Read these numbers with care.** These are small counts:
- 2 of 6 wrong held-out lines caught puts a 95% interval for recall of about 10% to 70%;
- 2 of 2 flags right puts precision at no less than about 34%;
- the first set's 14 of 15 is about 70% to 99% at the same confidence, but on lines the rules
  were written for;
- three of the 6 held-out wrong labels were judgement calls: "one kick away" after the winning
  kick, "the halfway mark" at 12 overs, and Kohli's "two sixes".

The labels are a model's reading of the data, so they can be wrong too, as the two cricket streak
lines above may show.

**Omissions are counted apart.** The live check also retries a line that leaves out a milestone or
how a shot ended. The labels never call an omission wrong, so the figures above leave those reasons
out. Counted as the live check counts them, the precision falls to 18% on the held-out set (9 lines
labelled right also flagged) and to 50% on the first set (14). Each such line is regenerated once.
If the retry fails too, the line built from the data is said instead, and the failed try goes to
the producer's fix queue.

Rerun it with `uv run python -m eval.checker_eval` (the first set) and
`uv run python -m eval.checker_eval --heldout`. The test
[`tests/test_checker_eval.py`](../tests/test_checker_eval.py) fails if the checker drops below what is
measured today on either set. [`tests/test_recall_classes.py`](../tests/test_recall_classes.py) holds a
wrong and a right line for each of the six rules.

### Line check beside the rules

The same labelled lines, lead lines only, through Line check: a keyed run of
[`eval/linecheck_eval.py`](../eval/linecheck_eval.py), recording off: the first set on integration
`b4d4cf4`, the held-out set as `/stats` serves it ([`eval/linecheck_heldout.json`](../eval/linecheck_heldout.json), #317). Its held-out
result is a row of the README's table. A Line check flag only sends the line to the producer's fix queue; it never stops the line
being said. The samples are small: one catch moves these a lot.

## The problem

On 10 October 2026 Sky Sports launched live descriptive audio commentary for the Premier League:
one match a day each game week, about 109 of the league's 380 games a season
([ISPreview](https://www.ispreview.co.uk/index.php/2026/10/sky-sports-to-introduce-live-subtitles-and-live-descriptive-audio-commentary.html)).
A major broadcaster now ships audio description for live football, for about 109 of the Premier
League's 380 games ([What Hi-Fi?](https://www.whathifi.com/streaming-entertainment/tv-streaming-services/sky-announces-a-significant-step-forward-for-its-accessible-premier-league-coverage-and-its-a-promising-move)). Touchline is for every match with a data feed.

At least 2.2 billion people have a near or distance vision impairment
([WHO](https://www.who.int/news-room/fact-sheets/detail/blindness-and-visual-impairment)). For a fan
who can't see the screen, a match that nobody describes is a match they can't follow.

Outside Sky's matches, live audio description is voluntary and patchy. In UK football it is run club
by club, at the ground: a 2015 Level Playing Field survey of the 20 Premier League clubs found only
four with in-house commentary by trained audio describers
([Disability News Service](https://www.disabilitynewsservice.com/premier-league-should-be-ashamed-of-treatment-of-blind-fans/)).
Rules don't close the gap: in the US the FCC requires the top networks to describe 87.5 hours a
quarter, and live or near-live programming is exempt
([Federal Register](https://www.govinfo.gov/content/pkg/FR-2024-03-12/html/2024-05186.htm)). Where a
club does describe its matches, the effort can come from the fans: at Wrexham the disabled supporters'
association, with local sponsors, placed a £4,000 audio-description project with the club, four
years of running it included, at no cost to the club
([Level Playing Field](https://www.levelplayingfield.org.uk/news-item/audio-description-commentary-at-wrexham-afc)).

A model can describe the rest, if it speaks while the moment is still on screen and costs little
enough to run for every match. The live site's [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)
reports both as they stand: first word, cost per line and cost per replay.

**Who it's for:** fans who can't see the screen. **Who pays:** rights holders, leagues, clubs and
streaming platforms, for the long tail of matches they stream with no describer.
