# The demo

**Touchline: the describer that checks itself. For the match nobody described.** The story opens on a
Women's Super League match that had no described broadcast, shows the describer catching its own
mistakes, sends one it couldn't fix to a producer, and ends on what it costs. About 2:45, on the live
URL, with the sound on. Anything shown outside our product, such as Mubit's console, is said aloud
as such. Every number spoken is read off the live [`/stats`](https://night-shift-5zvig7nbvq-ew.a.run.app/stats)
on the day; none is written here to be repeated.

Videos embed where YouTube allows it; otherwise the tile says so and links to YouTube, and the
commentary still plays on the match's own clock.

## Before going on

- Open the wall, <https://night-shift-5zvig7nbvq-ew.a.run.app>, and check
  [`/health`](https://night-shift-5zvig7nbvq-ew.a.run.app/health) says ok.
- Warm the voices: with the ElevenLabs key in the environment, `uv run python -m core.voice` speaks a
  short line in every voice and prints FAILED for any that fail. A cold library voice can fail its
  first line.
- Open **Review** once: note a flagged line to fix in step 4.
- Have Mubit's console open on the Adapters page, signed in.

## The script

| # | Time | On screen | Say |
|---|---|---|---|
| 1 | 0:00 | Black, then the wall. Tap **Brighton v Bristol City**, the wide tile marked "No described broadcast" | Nothing for ten seconds: let the room hear it. Then: "That match had no described broadcast. Touchline described it from the match data, in a replay, as if live." |
| 2 | 0:20 | The **Proof** card: First time, Auto-fixed, To a human | "Before it speaks, it checks every number against the data. When a call is wrong, it tries again; this count is the calls it fixed itself, before anyone heard them." |
| 3 | 0:40 | **Review**: a line the retry couldn't fix, with the check's reasons | "When the retry still fails, it doesn't guess. It says a line built from the data, and sends the call to a producer, with the reason." |
| 4 | 1:00 | Press **Fix** on that line, type the right line, save | "A producer fixes it in one line. A wrong leader is the error that breaks a blind fan's trust." |
| 5 | 1:25 | Mubit's console, Adapters | "Every fix is recorded in Mubit, to train a smaller describer of our own." Say the best version's score as it is; call it better only if Mubit marks it Passed. |
| 6 | 1:55 | Kobe's 81 or the World Cup final; type "Where are we?" or "How did Messi score?" in **Ask** | "A fan can ask anything, any time, in the same voice." |
| 7 | 2:15 | The **Proof** card: calls, fixed by itself, sent to a person; the cost per match | "Across seven matches: [calls], [fixed itself] fixed by itself, [to a human] sent to a person. About [cost] a match, voice included." Read each figure off the card. |
| 8 | 2:35 | The wall | "Touchline. The describer that checks itself. For the match nobody described." |

The cost per match is the mean over full replays of these highlights, not the price of a whole
90 minutes: never say it as one.

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
  then show the Proof card's counts and go to step 5.

## Do not say

"checks every fact", "a million matches", "lower leagues get none", "the law requires it", or any
cost per match other than the one on the Proof card.
