# Touchline: the evidence

**Mubit, step by step:** a producer's fix to a Score check example to a tested version, with ledger rows and request ids: [docs/mubit.md](mubit.md).

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

**Mubit, exactly as its console shows it.** Mubit's console overview, read on 25 October 2026 at
00:14 UTC, shows 11 tasks, 8 adapters and 0 serving. Mubit keys a task on its fingerprint: the
system prompt, the tools, the output format and the model. Each prompt change started a new task, so
our recorded commentary is split across several tasks rather than one. The overview lists these
eight adapters as they stood at 00:14 UTC; it no longer reports examples per task. At that reading
none was ready against Mubit's 95% target, and the console counted 0 serving. A later read, at
06:27 UTC on 25 October, shows 12 tasks and 9 adapters; its serving count and target were not read
([README figures](#readme-figures)).

| Task | Version | Status | Quality | Test cases |
|---|---|---|---|---|
| Check one line of… (Score check; the console cuts the name short; created about 1 h before) | v1 | Not ready yet | 33.3% | 12 |
| Live sports commentator | v2 | Not ready yet | 4.2% | 24 |
| Live sports commentator 2 | v1 | Not ready yet | 58.3% | 24 |
| Live television commentator | v2 | Not ready yet | 34.8% | 23 |
| Live television commentator 2 | v2 | Not ready yet | 28.6% | 21 |
| Live television commentator 3 | v1 | Training v2 | 55.8% | not shown |
| Live television commentator 4 | v1 | Not ready yet | 30.0% | 30 |
| Live television commentator 5 | v2 | Not ready yet | 28.6% | 21 |

What we did about it: [Line check](#how-it-uses-mubit), one frozen task whose answer key comes from
code, with its recorded checks and the producers' fixes. Beside the rules (#298), it checks each new lead
line; replays of stored lines make no new Line check call (its count is `linecheck` on [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)). Its
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

Every LLM call goes through Mubit. Calls with recording enabled supply training data for a small
commentator model; eligible producer fixes go into the original task as corrections. A version is
used only once it passes
Mubit's test, and none had at the 00:14 UTC console reading ([as its console shows it](#correction-loop-with-evidence)). That smaller model is what would make a commentator for every match affordable.

1. **Every call goes through Mubit.** Each moment line is one call to Mubit's Anthropic endpoint
   (`claude-haiku-4-5`, recorded for training runs; unrecorded on the default live key), or two when
   the agent uses its one permitted round of tools. The analyst's stat lines and the lead's replies
   are one call each to `claude-sonnet-5-5`, unrecorded. There is one
   session per match, and no model is called from the browser
   ([`agent/commentator.py`](../agent/commentator.py)).
2. **One task for every sport.** The system prompt, message template, tools and model are the same,
   byte for byte, for football, cricket, basketball and F1; the sport goes in the message. Mubit sees
   one task to learn from ([`agent/prompt.md`](../agent/prompt.md), [`agent/tools.json`](../agent/tools.json)).
3. **Real matches only for commentary.** [`scripts/replay_matches.py`](../scripts/replay_matches.py) replays distinct
   real football and cricket matches, never padded or repeated calls. Held-out matches and the demo
   matches are never replayed, so the trained model is judged only on matches it never saw. Score
   check's examples are not all real lines: of the 2,161 sent (`/stats` saved 23:08 UTC, 24 Oct),
   2,101 come from the code's answer key, and these include planted copies of real lines with one
   score number changed, labelled wrong by that answer key ([`eval/seed_scorecheck.py`](../eval/seed_scorecheck.py)).
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
7. **The trained model is measured, not assumed.** Each prompt change started a new task. Mubit's
   console at 00:14 UTC on 25 October showed 11 tasks and 8 adapters (seven commentary tasks and
   Score check), the best commentary task at 58.3% against a 95% target, and 0 serving; at 06:27 UTC
   it showed 12 tasks and 9 adapters ([`data/mubit_console.json`](../data/mubit_console.json)). The app
   does not call an adapter ([the console read](#correction-loop-with-evidence)). The
   aim is that one matches the big model at lower cost; we make no claim that any does.
8. **Line check, a task with exact answers.** A separate, frozen recorded task checks a stored line against
   its moment's facts and answers one JSON object: score, leader, player total and event, each
   `ok`, `wrong` or `not_said` ([`eval/linecheck.py`](../eval/linecheck.py),
   [`eval/seed_linecheck.py`](../eval/seed_linecheck.py)). The answer key comes from code, never a
   model, and a line code can't decide is left out. Some examples are **planted**: a right line with
   one field changed so it is wrong, marked `planted: true`. They balance the labels; they are not
   real errors the commentator made. Every line of the WSL match (3913122) and the F1 race (9636)
   is held out and never sent to Mubit. Beside the rules (#298), it checks each new lead line; stored
   replays make no new Line check call (`linecheck` on [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)). A flag sends the
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

## Keyboard and screen reader

Each keyboard or screen-reader claim the README or the site makes, the code that does it, and the test
that covers it. Paths are under `web/`.

| Claim | Code | Test |
|---|---|---|
| **E** closes your eyes, but not while typing or with Ctrl, Cmd or Alt | [`src/eyes.ts:2`](../web/src/eyes.ts#L2), [`src/components/Live.tsx:211`](../web/src/components/Live.tsx#L214) | [`src/live.test.ts:251`](../web/src/live.test.ts#L251) (the key rule; no browser test presses E) |
| Close your eyes is a toggle button with its key named (`aria-pressed`, `aria-keyshortcuts="E"`); the cover keeps the line and the score, and the player runs on | [`src/components/Controls.tsx:63`](../web/src/components/Controls.tsx#L63), [`src/components/Live.tsx:256`](../web/src/components/Live.tsx#L259) | [`src/live.test.ts:215`](../web/src/live.test.ts#L215), [`:231`](../web/src/live.test.ts#L231) |
| **T** opens the Teams tab and moves focus to its heading | [`src/components/Live.tsx:198`](../web/src/components/Live.tsx#L201), [`:322`](../web/src/components/Live.tsx#L326) | [`e2e/teams.spec.ts:61`](../web/e2e/teams.spec.ts#L61), [`e2e/a11y.spec.ts:108`](../web/e2e/a11y.spec.ts#L108) |
| **W** asks "Where are we?" (the button's title says so) | [`src/components/LineLog.tsx:175`](../web/src/components/LineLog.tsx#L175), [`:185`](../web/src/components/LineLog.tsx#L185) | [`e2e/keyboard.spec.ts:55`](../web/e2e/keyboard.spec.ts#L55) |
| **Talk** pauses the match; Enter starts it, Escape ends it and resumes, also while connecting | [`src/components/Converse.tsx:45`](../web/src/components/Converse.tsx#L45), [`:82`](../web/src/components/Converse.tsx#L82) | [`e2e/talk.spec.ts:56`](../web/e2e/talk.spec.ts#L56), [`:84`](../web/e2e/talk.spec.ts#L84), [`:125`](../web/e2e/talk.spec.ts#L125) |
| 12 s of silence after the commentator ends Talk | [`src/converse.ts:11`](../web/src/converse.ts#L11), [`src/components/Converse.tsx:62`](../web/src/components/Converse.tsx#L62) | [`e2e/converse-lifecycle.spec.ts:114`](../web/e2e/converse-lifecycle.spec.ts#L114) (fake clock) |
| The caption is a live region only while the voice is silent, so a screen reader never reads over it | [`src/components/Caption.tsx:22`](../web/src/components/Caption.tsx#L22), [`src/components/Live.tsx:222`](../web/src/components/Live.tsx#L225) | [`e2e/a11y.spec.ts:158`](../web/e2e/a11y.spec.ts#L158) (off while voiced), [`e2e/keyboard.spec.ts:103`](../web/e2e/keyboard.spec.ts#L103) (on while silent) |
| An answer is announced: "Answer ready" while voiced, its text when silent | [`src/components/LineLog.tsx:67`](../web/src/components/LineLog.tsx#L67) | [`e2e/a11y.spec.ts:168`](../web/e2e/a11y.spec.ts#L168) (voiced), [`e2e/keyboard.spec.ts:103`](../web/e2e/keyboard.spec.ts#L103) (silent) |
| State changes are announced: playing, paused, screen covered, off air, voice off | [`src/components/Live.tsx:244`](../web/src/components/Live.tsx#L247), [`:415`](../web/src/components/Live.tsx#L419) | [`e2e/a11y.spec.ts:156`](../web/e2e/a11y.spec.ts#L156), [`src/live.test.ts:142`](../web/src/live.test.ts#L142) |
| Keyboard only, in order: Tab to a match, Enter, it is called aloud; Tab to Ask, type, Enter | [`src/components/Wall.tsx:141`](../web/src/components/Wall.tsx#L141), [`src/components/LineLog.tsx:192`](../web/src/components/LineLog.tsx#L192) | [`e2e/a11y.spec.ts:131`](../web/e2e/a11y.spec.ts#L131) |
| A visible focus ring; Tab never enters the video embed | [`src/App.css:21`](../web/src/App.css#L21), [`src/player.ts:125`](../web/src/player.ts#L125) | [`e2e/a11y.spec.ts:152`](../web/e2e/a11y.spec.ts#L152), [`src/player.test.ts:61`](../web/src/player.test.ts#L61) |
| A sheet (voice, fix, shot map) takes the focus, Escape closes it, and focus returns | [`src/focus.ts:5`](../web/src/focus.ts#L5) | [`e2e/a11y.spec.ts:172`](../web/e2e/a11y.spec.ts#L172) (the voice sheet) |
| One h1 per live page, then an h2 per panel | [`src/components/Live.tsx:247`](../web/src/components/Live.tsx#L250) | [`src/live.test.ts:317`](../web/src/live.test.ts#L317), [`:333`](../web/src/live.test.ts#L333) |
| Follow: a labelled search box (combobox, Escape closes the list); the card is a region named "Following <player>" | [`src/components/FollowPicker.tsx:39`](../web/src/components/FollowPicker.tsx#L39), [`src/components/ProfileCard.tsx:28`](../web/src/components/ProfileCard.tsx#L28) | [`e2e/keyboard.spec.ts:73`](../web/e2e/keyboard.spec.ts#L73) (at 390 and 1280 px) |
| No serious or critical axe finding on the wall, the live page and the review queue, at 390 and 1280 px, also with the fallback font and 200% text | the pages above | [`e2e/a11y.spec.ts:91`](../web/e2e/a11y.spec.ts#L91), [`:117`](../web/e2e/a11y.spec.ts#L117) |

Every claim here has a test. [`tests/test_readme_claims.py`](../tests/test_readme_claims.py) fails if a link
above stops pointing at its code or its test.

## README figures

Each figure the README states, where it comes from, and the test that fails if the two drift apart.
The tests are [`tests/test_readme_numbers.py`](../tests/test_readme_numbers.py) (N) and
[`tests/test_readme_claims.py`](../tests/test_readme_claims.py) (C).

| Figure | Source | Test |
|---|---|---|
| About $0.45 a replay, voice included, over 84 replays | [`eval/live_stats_2026-10-24.json`](../eval/live_stats_2026-10-24.json) `cost_per_match_usd`, `matches_measured` (live `GET /stats`, saved 23:08 UTC, 24 Oct) | N `test_the_readme_live_figures_are_the_saved_stats_read` |
| 2,161 examples sent to training, 60 from producer fixes | the same file, `scorecheck` | N, same test |
| 46 matched, 5 corrected, 9 not corrected | the same file, `scorecheck.from_fixes_by_kind` (they add up to the 60) | C `test_the_fixes_breakdown_and_console_counts_are_the_saved_reads` |
| 74 of 74 held-out lines agree | the same file, `scorecheck` | N `test_the_readme_live_figures_are_the_saved_stats_read` |
| 11 tasks, 8 adapters, 0 serving; Score check v1 33.3% on 12 test cases, best commentary 58.3%, of a 95% target (00:14 UTC, 25 Oct) | [`data/mubit_console.json`](../data/mubit_console.json) `earlier`, read by hand | N `test_the_side_by_side_panel_and_readme_match_the_console_read`, C `test_the_fixes_breakdown_and_console_counts_are_the_saved_reads` |
| 12 tasks, 9 adapters; "Check one line of 2" (Line check or Score check; the console cuts the name short, so which is not confirmed) has 2,235 calls and 192 kept examples, and its first version, testing v1, shows 94.6%, status Testing, not live (06:27 UTC, 25 Oct) | [`data/mubit_console.json`](../data/mubit_console.json), read by hand | C `test_the_console_reading_is_dated_sourced_and_claims_no_adapter` |
| Ask: 32 of 33 right, 1 wrong, 0 refused; the wrong one is row 24 at Lakers 120-102 | [`eval/ask_eval_keyed_20261025.txt`](../eval/ask_eval_keyed_20261025.txt), the keyed run's output | C `test_the_ask_figures_are_the_saved_keyed_run` |
| Terland: moments 18, 34 and 35 of the six later lines say "the Seagulls"; 94:48 "The Seagulls go three-two up" | [`eval/fix_then_later_live_20261024.txt`](../eval/fix_then_later_live_20261024.txt), the live run in #501 | C `test_the_terland_run_names_the_later_moments_saying_the_seagulls` |
| The check table (held-out and first set) | [`eval/checker_eval.py`](../eval/checker_eval.py), [`eval/linecheck_heldout.json`](../eval/linecheck_heldout.json), written by [`eval/readme_numbers.py`](../eval/readme_numbers.py) | N `test_the_readme_check_table_is_todays_checker_eval_output`, `test_the_stored_held_out_rules_count_is_todays_rules` |
| One more catch is about 17 points | 1 of the table's 6 held-out wrong lines | C `test_one_more_catch_is_about_seventeen_points_and_the_first_word_about_half_a_second` |
| First word in about half a second | the saved `/stats`, `by_speaker.lead.first_word_ms_p50` (547 ms) | C, same test |
| 620 football matches in the graph | the shipped store in [`data/graph/`](../data/graph): 612 from StatsBomb in four competition-seasons and 8 NWSL 2018 results from [`data/results/`](../data/results) | C `test_the_graph_holds_the_football_matches_the_readme_counts` |
| The budget guard's defaults: 4, 10, 20, 50 | [`core/guard.py`](../core/guard.py) `Guard` | C `test_the_budget_table_is_the_guards_defaults`; what each limit does: [`tests/test_guard.py`](../tests/test_guard.py) |
| Two files over the 1,000-line rule | the repo's files | C `test_the_files_over_the_line_rule_are_the_two_the_readme_names` |
| A fix without the producer token gets 401; one the data contradicts gets 422 and never reaches Mubit | [`core/app.py`](../core/app.py) `fix_line` | [`tests/test_fix_heard.py`](../tests/test_fix_heard.py) `test_a_fix_needs_the_producer_token_once_the_deploy_sets_one`, `test_a_fix_the_data_contradicts_or_over_200_characters_gets_422_and_stores_nothing` |
| Talk ends after 12 s of silence | [`web/src/converse.ts`](../web/src/converse.ts) `SILENT_MS` | [`web/e2e/converse-lifecycle.spec.ts`](../web/e2e/converse-lifecycle.spec.ts) (fake clock), and the keyboard table above |
| Every Mubit call site | the "Where Mubit is called" list | N `test_the_readme_mubit_call_sites_point_at_the_calls` |
| Known limitation: two stored analyst admissions replay, and a fix to an analyst line is not heard | [`core/insight.py`](../core/insight.py) `admits`, [`core/replay.py`](../core/replay.py) `run_replay`; the cause in [`agent/analyst.md`](../agent/analyst.md) | C `test_two_stored_analyst_admissions_pass_the_check_and_a_fix_to_one_is_not_heard` |
| Known limitation: at the cold open the server already gives the first mapped event | [`core/app.py`](../core/app.py) `asked_so_far`, #520; the page-only gate is #519 | C `test_at_the_cold_open_the_server_already_gives_the_first_mapped_event` |
| Known limitation: Talk says a sentence written before a tool call | [`core/converse.py`](../core/converse.py) `speak` | C `test_talk_says_a_sentence_written_before_a_tool_call` |
| Known limitation: no headless test holds a real Talk conversation | [`tests/test_converse.py`](../tests/test_converse.py) (server, headless), [`web/e2e/talk.spec.ts`](../web/e2e/talk.spec.ts) (faked session) | not testable headless: a browser, a microphone and the ElevenLabs agent |

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

Touchline's own cost, beside those: about $0.45 a replay, voice included, over 84 replays of these
highlights (live `/stats` `cost_per_match_usd` and `matches_measured`, saved on 24 Oct 2026 at 23:08 UTC
as [`eval/live_stats_2026-10-24.json`](../eval/live_stats_2026-10-24.json)). It is a cost to run, not a price.

A model can describe the rest, if it speaks while the moment is still on screen and costs little
enough to run for every match. The live site's [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)
reports both as they stand: first word, cost per line and cost per replay.

**Who it's for:** fans who can't see the screen. **Who pays:** rights holders, leagues, clubs and
streaming platforms, for the long tail of matches they stream with no describer.
