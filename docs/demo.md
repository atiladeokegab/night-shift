# The demo

**Touchline: the describer that checks itself. For the match nobody described.** Planned cut: **1:50,
hard stop 1:58**, under the 2:00 limit. Record it on the live URL with the sound on and a narrator's
voice laid over the screen. It runs in the same order as the README's
[On stage](../README.md#on-stage): a match described with the **Proof** card, a wrong line caught
before air, a producer's fix that the next lines on that match carry, the fix sent to Score check
training, Mubit's console, then who buys it. Ask, Talk, Follow a player, Teams and the shot map stay
in the product but are not in the film. Anything shown outside our product, such as Mubit's
console, is said aloud as such. Time the finished cut before submitting.

Videos embed where YouTube allows it; otherwise the tile says so and links to YouTube, and the
commentary still plays on the match's own clock.

## Before going on

- Open the wall, <https://night-shift-5zvig7nbvq-ew.a.run.app>, and check
  [`/health`](https://night-shift-5zvig7nbvq-ew.a.run.app/health) says ok.
- Run `make demo-check` and go on only when every line says PASS: health, a first line within 30 s,
  its ElevenLabs audio, the voice not on browser fallback, spend under the daily budget, and Line check
  in `/stats`.
- Warm the voices: with the ElevenLabs key in the environment, `uv run python -m core.voice` speaks a
  short line in every voice and prints FAILED for any that fail. A cold library voice can fail its
  first line.
- Both fixes in the film are already made on live, once each. **Do not fix either line again**:
  Terland's 30:57 line at Brighton v Bristol City (`3913122`, moment 8), made by
  [`scripts/fix_then_later.py`](../scripts/fix_then_later.py), and Cahill's goal at Chelsea v
  Tottenham Hotspur (`3754092`, 57:41), whose **Sent to training** panel is shot from stills.
- Have Mubit's console open on the **Score check** task, signed in. Its figures are only those in
  the evidence page's [correction loop](evidence.md#correction-loop-with-evidence) section; read
  them again on the day.
- Record at 1280 wide. Record the voice separately, then lay it over the screen. Do a dry take
  first: the opening lines vary by run.

## The script

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:23.6 | **Brighton v Bristol City** (`/?match=3913122`) playing with video, ON AIR. Press **E** (**Close your eyes**): the picture goes black, only the line and the score stay, the voice carries on. Then the **Proof** card: auto-fixed, this match and all matches, then the cost per full replay | "Every week a club's media team cuts highlights. A fan who can't see them gets nothing from the pictures. Close your eyes." Then let one line play. |
| 2 | 0:23.6–0:35.3 | **Orlando v North Carolina** (NWSL, 2018): Denise O'Sullivan's 39:39 line, tagged **Auto-fixed** | "Before it speaks, it checks the score, the leader and the numbers against the data. This line was wrong. It fixed itself before anyone heard it." |
| 3 | 0:35.3–1:00.3 | Three cards, word for word from the live run: 30:57, "Elisabeth Terland! Brighton take the lead, one nil!"; the producer's fix, "Elisabeth Terland scores! The Seagulls lead one-nil." ("Call Brighton the Seagulls"); 94:48, before "Elisabeth Terland! Brighton take the lead, 3-2!" and after "Elisabeth Terland! The Seagulls go three-two up with that left-footed half volley!" | "A producer fixes one line. The next lines on this match carry the producer's fix." |
| 4 | 1:00.3–1:10.3 | Cahill's fix on **Review**: the **Sent to training** panel, "Line as said: wrong", "Fixed text: ok", **Score check examples: 2,161 → 2,163**, "Training run pending" | "The fix also goes to Mubit as training data: two Score check examples." |
| 5 | 1:10.3–1:30.3 | Mubit's console, the **Score check** task: its examples, then its version and test score | "This is Mubit's console, outside our app: the fix is a Score check example." Then say the console as it is: **training, not serving**. Call a version better only if the console marks it Passed, and never say the app uses it. |
| 6 | 1:30.3–1:42.3 | The buyer card | "Built for the streaming platforms that carry the WSL and NWSL. It costs about forty-five cents a replay to run, voice included." |
| 7 | 1:42.3–1:50.3 | Logo, tagline, the live URL | "Touchline. The describer that checks itself." |

The cost is the README's figure, about $0.45 a replay with the voice included, from live `/stats` on
24 Oct: the mean over full replays of these highlights, not a whole 90 minutes, and never a price
for the buyer.

Only moments 18, 34 and 35 of the Brighton run took up "the Seagulls". The run's other later lines
changed through ordinary variation between generations: never claim every later line changed
because of the fix.

Brighton's ground has in-stadium description: say "no described broadcast that we could find",
never "no description".

## Jump to the big moment

Every tile has a **Jump to the big moment** pill at its top right. It opens the live page with the
video 10 s before the match's peak and the commentary starting there: nothing earlier is called, but
the commentator knows the score. Use it to reach a peak inside the time.

Seconds are from when the video starts playing (a second or two after the tap), from the checked-in
video maps (`data/video/`); check them with a stopwatch before going on.

| Match | Button | Video starts | Beats (s after play) | Ends |
|---|---|---|---|---|
| Kobe's 81 v Toronto | Jump to the big moment | 23:43 | 10 free throw for 80 · 20 free throw for 81 · 40 Bonner's jumper | 79 buzzer |
| Jordan's last shot as a Bull | Jump to the big moment | 22:34 | 10.5 the steal · 23.5 the shot | 54 buzzer |
| India v Pakistan | Jump to the big moment | 13:56 | 10 last-over wicket · 33 six · 102 wicket | 150 last ball |
| Messi v Mbappé | Jump to the big moment | 10:18 | 10.8 first penalty, then one about every 6 s | 46.4 full time |
| Verstappen, P17 to P1 | Jump to the big moment | 2:08 | 10.4 into P1 | 24.2 chequered flag |
| Battle of the Bridge | Jump to the big moment | 1:54 | 10.4 Hazard's equaliser | 10.4 |
| Brighton v Bristol City (WSL, 2024) | Jump to the big moment | 2:41 | 10 Carrie Jones's equaliser · 40 Terland's winner | 78 full time |

## If something fails

- **A tile says the video can't play here:** the commentary runs on the match's own clock without
  the picture. Carry on.
- **The badge reads OFF AIR:** the model provider is out of credit, so no new lines come. Say so,
  then show the Proof card's counts and go to shot 3: shots 3 and 4 are cards and stills.
- **The console hasn't shown the fix yet:** show Score check's example count and version, and say
  the fix is on its way; never claim it arrived.

## Do not say

"checks every fact" (it checks the score, the leader, the key numbers and events), "learns live",
"the model updated", anything implying the app uses a trained version, or that every later line
changed because of the fix. Also: "a million matches",
"lower leagues get none", "the law requires it", "$5 a match", "RNIB standard" or "RNIB approved",
or any cost other than about $0.45 a replay, voice included. The cost is what a replay costs to run,
never a price for the buyer. Name no streaming platform: "the
streaming platforms that carry the WSL and NWSL", never a company.
