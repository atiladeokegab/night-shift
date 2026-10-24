# The demo

**The promise: every match gets a commentator.** The peak is a goal called aloud over the broadcast
picture. The script runs two minutes.

Everything runs from main's deployed URL, with the sound on. Anything shown outside our product, such
as Mubit's console, is said aloud as such.

## Before going on

Open three tabs:

1. **Wall**, <https://night-shift-5zvig7nbvq-ew.a.run.app>: the home page, every match playing muted.
2. **Stage**, <https://night-shift-5zvig7nbvq-ew.a.run.app/stage>, cued on the goal. The wall's
   full-screen video can't be dragged and reaches the goal about 3 minutes 40 seconds after a tap, so
   the goal is cued here, where the YouTube player has its own controls. In this order:
   1. Tap Football. Wait until the bar under the video reads "15 held" (about 20 seconds): every line
      is written and waiting for its moment.
   2. Pause the video with its own controls. While it is paused, the commentary waits.
   3. Drag the video to 5:05. The bar now reads "next line 5:15". If it shows an earlier time, the
      lines weren't all held yet: wait for "15 held" and drag again.
3. **Mubit's console**, signed in, showing the requests for our task.

Check `/health` says ok.

**Warm both voices.** A library voice that hasn't spoken for a while can fail its first line: in the
headless check, the first cricket audio returned 503 and then 200 on retry. On the wall tab:

1. Tap India v Pakistan and wait until Raju speaks one line, then tap ← Wall.
2. Tap Spain v England and wait until the first line is spoken, then tap ← Wall. Skip this if the
   Stage tab's cue already played a line aloud.

Once #83 is merged, `uv run python -m core.voice` (with the ElevenLabs key in the environment) warms
both voices from a terminal too. Still do the taps: they prove the voices play in the browser.

While the wall is open, read the proof panel's numbers and the adapter's state once, so the spoken
ones match the screen.

**If the highlights can't play** (a tile says "Highlights unavailable here", or /stage says "Video
unavailable"): /stage shows lines as they arrive, without waiting for a moment, so skip step 3. The
wall's full screen still keeps the commentary on the replay clock without the picture, so steps 2
and 4 work as written.

## The script

The section times are targets for a two-minute run, estimated rather than timed: no person has
rehearsed it against a clock yet. The waits inside them (the first call 6 seconds after a tap, the goal
10 seconds after play, Raju in 6 to 20 seconds) were measured on the deployed page (see the headless
check below).
*Italics* are what's on screen; the quoted text is spoken.

### 1. The promise (0:00–0:15)

*Wall tab: six matches, all playing, none of them called.*

"Tonight thousands of matches will be played that nobody calls. Fans get a ticker, or silence.
Touchline gives every match a commentator."

### 2. Tap into a match (0:15–0:30)

*Tap Spain v England, the 2023 Women's World Cup final. It goes full screen, and Lauren Hemp's early
chance is called about 6 seconds later (measured).*

"Tap a match, and the commentator takes it. It reads the real match data and calls each moment as it
reaches the picture."

### 3. The goal, the peak (0:30–0:55)

*Stage tab, paused at 5:05 on the same final. Press play. Olga Carmona's goal is called at 5:15,
10 seconds later (measured).*

"Here's the goal."

*Stop talking. Let the goal be called aloud, with the subtitle.*

"That line was written from the real match data and held until the goal reached the picture."

### 4. Another sport, same commentator (0:55–1:20)

*Wall tab. Tap ← Wall, then India v Pakistan, the 2022 T20 World Cup. Babar Azam's wicket is called
by Raju, in 6 to 20 seconds (measured).*

"Same commentator, same prompt, different sport, and a cricket voice."

### 5. The fix (1:20–1:35)

*In the Lines card, tap Fix on the wicket line. The sheet shows what Touchline said, with the line
ready to correct. Type the correction and send. The line shows Fixed and the proof panel's fix count
goes up by one.*

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

### 7. Close (1:55–2:00)

"Every match deserves a commentator. Now every match can have one."

## Rehearsal

Rehearse once on the deployed URL before recording, then note here the date, the commit deployed on
main and the total time. Check in particular:

- the Stage tab, paused at 5:05, calls the goal at 5:15 once played;
- the voice changes when the sport changes;
- a fix shows as Fixed and the proof panel's fix count goes up by one.

Retake the README's live-goal.png once #80 is deployed: it still shows "Spain Women's", which #80
corrects.

### Headless check, 2026-10-24 about 00:15 UTC

Each step was checked on the deployed URL (main at 42f73cc, the wall live) in headless Chrome on our
build server. This is not the timed rehearsal, which still needs a person.

- **YouTube refused to play in headless Chrome** (error 150; tiles say "Highlights unavailable here"
  or stay black). YouTube lists all six videos as embeddable, so this is most likely the headless
  browser on a cloud server. Confirm playback on the demo laptop.
- **Wall:** six tiles. Tapping Spain v England went full screen, and the first call came 5.9 s later.
  ← Wall took 0.1 s. India v Pakistan's first call came 20.2 s after the tap; that run's first audio
  request returned 503, and the same request returned 200 in 2.5 s when retried.
- **Stage, with a stand-in for the player's clock:** football held all 15 lines 18 s after the tap,
  and cricket all 32 after 41 s. Seeking before the lines were held left the bar on "next line 0:09"
  for 75 s while paused; seeking after they were held showed "next line 5:15" (or "13:23") at once.
  Played from there, the goal was called 10 s later and Kohli's six 8 s later, each with audio.
- **Fix** opens the sheet with the line prefilled. It was not sent, to keep test fixes out of the
  training data. The proof panel reads "Not trained yet" for the adapter.
