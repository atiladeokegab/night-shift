# The demo

**The promise: every match gets a commentator.** The peak is Kobe Bryant's 81st point called aloud
over the NBA's own broadcast picture. The script runs two minutes.

Everything runs from main's deployed URL, with the sound on. Anything shown outside our product, such
as Mubit's console, is said aloud as such.

**One match is commentary only.** Messi v Mbappé is a video whose owner blocks embedding: its tile
and page show a still and a "highlights on YouTube" link, and the commentary runs on its own clock.
The demo uses three that embed: Kobe's 81, Jordan's last shot and India v Pakistan. The Battle of the
Bridge (Chelsea v Tottenham, 2016) and Verstappen's P17 to P1 at Interlagos (2024) embed too; they
replaced Spain v England and Hamilton at Silverstone, whose videos would not (#114).

## Before going on

Open three tabs:

1. **Wall**, <https://night-shift-5zvig7nbvq-ew.a.run.app>: the home page, one tile per match.
2. **Stage**, <https://night-shift-5zvig7nbvq-ew.a.run.app/stage>, cued on Kobe's 81st point. The
   wall's full-screen video can't be dragged and reaches the 81st point 16 minutes after a tap, so the
   peak is cued here, where the YouTube player has its own controls. In this order:
   1. Tap Kobe. The video loads at 8:00, and the first line is due at 8:10.
   2. Pause the video at once with its own controls, before 8:10. While it is paused, the commentary
      waits.
   3. Wait until the bar under the video reads "20 held": every line is written and waiting for its
      moment.
   4. Drag the video to 23:45. The bar now reads "next line 23:53". If it shows an earlier time, the
      lines weren't all held yet: wait for "20 held" and drag again.
3. **Mubit's console**, signed in, showing the requests for our task.

Check `/health` says ok.

**Warm both voices.** A library voice that hasn't spoken for a while can fail its first line: in an
earlier headless check, the first cricket audio returned 503 and then 200 on retry.

1. From a terminal, with the ElevenLabs key in the environment, run `uv run python -m core.voice`. It
   speaks a short line in every voice, the sport picks included, and prints FAILED for any that fail.
2. Still do the taps, which prove the voices play in the browser. On the wall tab, tap India v
   Pakistan and wait until Raju speaks one line, then tap ← Wall.
3. Tap Jordan's last shot and wait until Sam, the basketball voice, speaks one line, then tap ← Wall.
   Jordan, not Kobe, so the Kobe tap in the script is still fresh.

While the wall is open, read the proof panel's numbers and the adapter's state once, so the spoken
ones match the screen.

**If the highlights can't play** (a tile says "Highlights unavailable here", or /stage says "Video
unavailable"): the commentary runs on its own clock, a line every few seconds, so skip the Stage
cue. The wall's full screen still keeps the commentary on the replay clock without the picture, so
steps 2 and 4 work as written.

**If the commentator is off air** (the badge reads OFF AIR, and the subtitle "Commentator is off air
for a moment"): the model provider has no credit left, so no new lines will come. Say so, and show
what it already did:

*Point at OFF AIR.* "Our commentator is off air right now: its model credit has run out. Here's what
it has already called." *Point at the proof panel's line count, then switch to the Mubit console
tab.* "This is Mubit's console, not our product: every line Touchline has called is stored here, one
request each, and it's the data our own commentator trains on." Then go to step 6, the proof. There
is no page in our product that lists the stored lines' text, so show them in Mubit's console.

## The script

The section times are targets for a two-minute run, estimated rather than timed: no person has
rehearsed this script against a clock yet. The video times (8:10, 23:53, 24:03) come from the match's
video map and its play-by-play; they were not seen live (see the check below).
*Italics* are what's on screen; the quoted text is spoken.

### 1. The promise (0:00–0:15)

*Wall tab: six matches, none of them called. Kobe, Jordan and India v Pakistan play muted; the other
three show their still, marked "Commentary only".*

"Tonight thousands of matches will be played that nobody calls. Fans get a ticker, or silence.
Touchline gives every match a commentator."

### 2. Tap into a match (0:15–0:30)

*Tap Kobe's 81 v Toronto, 22 January 2006. It goes full screen at 8:00, and Kobe's jumper for his
30th point is called at 8:10 (unverified live).*

"Tap a match, and the commentator takes it. It reads the real play-by-play and calls each moment as
it reaches the picture."

### 3. Eighty-one, the peak (0:30–0:55)

*Stage tab, paused at 23:45 on the same game, Lakers 120, Raptors 102. Press play. Kobe's free throw
for 80 is called at 23:53, 8 seconds later, and the free throw for 81 at 24:03, 18 seconds later.*

"Forty-three seconds left. Kobe's on the line."

*Stop talking. Let both free throws be called aloud, with the subtitle.*

"Those lines were written from the real play-by-play and held until each shot reached the picture."

### 4. Another sport, same commentator (0:55–1:20)

*Wall tab. Tap ← Wall, then India v Pakistan, the 2022 T20 World Cup. Babar Azam's wicket is called
by Raju, in 6 to 20 seconds (measured at 00:15 UTC, before the commentator went off air).*

"Same commentator, same prompt, different sport, and a cricket voice."

### 5. The fix (1:20–1:35)

*In the Lines card, pick a line and tap Fix. Lines are written afresh on every replay, so the line to
fix can't be chosen in advance. If a line has a factual slip, fix that. Otherwise, fix any line's
wording, for example American spelling ('defense' to 'defence') or a vaguer line to name the player.
Keep the correction to a word or two, typed in a few seconds. The sheet shows what Touchline said,
with the line ready to correct. Type the correction and send. The line shows Fixed and the proof
panel's fix count goes up by one.*

"Say a line is wrong. A producer corrects it right here. The fix is kept beside the original, and it
goes back through Mubit to train our own commentator."

### 6. The proof (1:35–1:55)

*The proof panel.*

"The model's first word comes in about half a second, and a line costs a fraction of a cent." Read
both numbers off the panel. The half second is the model's text, not the audio.

The one line on the tech: "Every call goes through Mubit, which trains a smaller commentator of our
own on these calls and every producer fix."

Then one of these, matching the adapter's state on the panel:

- **Adapter scored:** "Here's our trained commentator, scored against the big model on matches it
  never saw." Read the result off the panel as shown, and claim nothing beyond it.
- **Adapter not ready (the fallback):** *Point at the Lines card, then switch to the Mubit console
  tab.* "Every line you heard today came from the big model, Claude Haiku. This is Mubit's console,
  not our product: it holds those calls, the data our own commentator trains on. Our own commentator
  isn't trained yet, so we won't show you a number we don't have."

  On the off-air path no line was heard today, so open with "Every line Touchline has called came from
  the big model, Claude Haiku" instead, and skip pointing at the Lines card: it is empty.

### 7. Close (1:55–2:00)

"Every match deserves a commentator. Now every match can have one."

## Rehearsal

Rehearse once on the deployed URL before recording, with the commentator on air, then note here the
date, the commit deployed on main and the total time. Check in particular:

- the Stage tab reads "20 held", then "next line 23:53" after the drag to 23:45, and once played calls
  the free throws for 80 and 81 at 23:53 and 24:03, over the right shots;
- the wall's Kobe tap calls the 30-point jumper at 8:10;
- the voice changes when the sport changes;
- a fix shows as Fixed and the proof panel's fix count goes up by one.

### Kobe cue check, 2026-10-24 about 07:25 UTC

On the deployed URL (the /stage page byte for byte as on integration at 7634e23), in headless Chrome
on our build server, with the commentator off air:

- **Seen live:** /stage has a Kobe tab; tapping it loads the video at 8:00, and the bar read "Ⅱ 8:00 ·
  commentary waits" before YouTube refused to play headless (error 150). The stream's error turned the
  badge to OFF AIR with the subtitle "Commentator is off air for a moment". On the wall, Kobe, Jordan
  and India v Pakistan read "Tap to hear it called"; Messi v Mbappé, Spain v England and Hamilton read
  "Commentary only" (the last two since replaced, #114).
- **From the data, not seen live:** Kobe's replay has 20 moments, each with a video time, hence "20
  held". The video map puts the 30-point jumper at 8:10 (490.5 s), the free throws for 80 and 81 at
  23:53 and 24:03 (1433 and 1443 s), Bonner's jumper at 24:23 and the final buzzer at 25:02. These come
  from the checked-in video map; nobody has yet watched the video to confirm each shot is on screen at
  its time.

### Earlier headless check, 2026-10-24 about 00:15 UTC (the football script before #104)

Each step was checked on the deployed URL (main at 42f73cc, the wall live) in headless Chrome on our
build server. This is not the timed rehearsal, which still needs a person.

- **YouTube refused to play in headless Chrome** (error 150; tiles say "Highlights unavailable here"
  or stay black). Three of the six videos embed (Kobe's 81, Jordan's last shot and India v
  Pakistan); the other three are commentary only, because their owners block embedding (#104). For the
  three that embed, this is most likely the headless browser on a cloud server. Confirm playback on
  the demo laptop.
- **Wall:** six tiles. Tapping Spain v England (since replaced, #114) went full screen, and the first call came 5.9 s later.
  ← Wall took 0.1 s. India v Pakistan's first call came 20.2 s after the tap; that run's first audio
  request returned 503, and the same request returned 200 in 2.5 s when retried.
- **Stage, with a stand-in for the player's clock:** football held all 15 lines 18 s after the tap,
  and cricket all 32 after 41 s. Seeking before the lines were held left the bar on "next line 0:09"
  for 75 s while paused; seeking after they were held showed "next line 5:15" (or "13:23") at once.
  Played from there, the goal was called 10 s later and Kohli's six 8 s later, each with audio.
- **Fix** opens the sheet with the line prefilled. It was not sent, to keep test fixes out of the
  training data. The proof panel reads "Not trained yet" for the adapter.
