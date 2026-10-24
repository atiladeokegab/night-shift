# The demo

**Touchline: the describer that checks itself. For the match nobody described.** A film of **1:50,
hard stop 1:58**, under the 2:00 limit. It is recorded on the live URL with the sound on and a narrator's voice laid over the
screen; the cold open and the Ask shot carry the product's own voice. It shows three things and
then who buys it: **live commentary that checks itself before air** (a club's weekly highlights with
**Close your eyes**, a whole match nobody described, a line it fixed itself), **a producer's fix sent
to training** (the fix, its request id, the example count going up, the "Sent to training" panel),
and **Ask**. It ends on the buyer and what a replay costs. Talk, Follow a player, Teams and the shot
map stay in the product but are not in the film. Anything shown outside
our product, such as Mubit's console, is said aloud as such. Every number spoken is read off the
live [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats) or the Proof card on the day;
none is written here to be repeated. Time the finished cut before submitting.

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
- Open **Review** once and find the line for shot 4: Jordan's last game as a Bull, the layup where
  Utah lead 86–85 but the line says Chicago lead.
- The "Sent to training" panel (#411) needs the owner's Mubit key on the live service: with no
  recorder it says "No Score check example sent for this fix". Don't spend Jordan's line testing it.
- Record at 1280 wide. Record the voice separately, then lay it over the screen. Do a dry take
  first: the opening lines vary by run.

## The script

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00–0:10 | **Brighton v Bristol City** playing with video, ON AIR. Press **E** (**Close your eyes**): the picture goes black, only the line and the score stay, the voice carries on | "Every week a club's media team cuts highlights. A fan who can't see them gets nothing from the pictures. Close your eyes." Then let one line play. |
| 2 | 0:10–0:22 | Press **E** again. Cut to **Orlando v North Carolina** (NWSL, 2018), on its "Whole match, every key moment" label | "Touchline describes the highlights for them, every week, from the match data. And not only the reel: this whole match had no described broadcast that we could find, and Touchline called every key moment." |
| 3 | 0:22–0:35 | The **Proof** card's auto-fixed count, then one line it fixed | "Before it speaks, it checks the score, the leader and the numbers against the data. This line had the wrong score. It fixed itself before anyone heard it." |
| 4 | 0:35–0:50 | **Review**: the flagged line with the check's reason. Press **Fix** on Jordan's layup, type the right line, save | "When a retry still fails, it doesn't guess. A producer gets the line and the reason, and fixes it in one go. A wrong leader is the error that breaks a blind fan's trust." |
| 5 | 0:50–1:12 | The **Sent to training** panel under the saved fix: its request id, the two Score check examples ("Line as said: wrong", "Fixed text: ok"), the example count before → after, then its last row | "The fix goes to Mubit as training data: this is its request, these are the two examples it made, and the count went up." Then say the last row as it is: on "Training run pending", "no trained version serves yet". Name a version only as the panel names it, and never say the app uses it. |
| 6 | 1:12–1:27 | The **World Cup final** (`/?match=3869685&at=45`); type "Where are we?" in **Ask** | "A fan can ask anything, any time, in the same voice." |
| 7 | 1:27–1:50 | The **Proof** card: lines called, fixed by itself, sent to a person; the cost per match | "[called] called, [auto-fixed] fixed by itself, [to a person] sent to a person. Built for the streaming platforms that carry the WSL and NWSL: about [cost] a replay, voice included." Read each figure off the card. |
| 8 | 1:50–1:58 | Logo, tagline, the live URL | "Touchline. The describer that checks itself." |

The cost per match is the mean over full replays of these highlights, not the price of a whole
90 minutes: never say it as one. On 2026-10-24 `/stats` read `cost_per_match_usd` 0.35 over 79
replays, so "about 35 cents a replay"; say the card's figure on the day if it has moved.

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
  then show the Proof card's counts and go to shot 4.
- **The Sent to training panel shows no example:** say "the fix is saved beside the original" and go
  to shot 6.

## Do not say

"checks every fact" (it checks the score, the leader, the key numbers and events), "learns live",
"the model updated", or anything implying the app uses a trained version. Also: "a million matches",
"lower leagues get none", "the law requires it", "$5 a match", "RNIB standard" or "RNIB approved",
or any cost per match other than the one on the Proof card. Name no streaming platform: "the
streaming platforms that carry the WSL and NWSL", never a company.
