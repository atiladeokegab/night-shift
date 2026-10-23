# The demo

**The promise: every match gets a commentator.** The peak is a goal called aloud over the broadcast
picture. The script runs two minutes.

Everything runs from main's deployed URL, with the sound on. Anything shown outside our product, such
as Mubit's console, is said aloud as such.

## Before going on

Open three tabs:

1. **Stage**, <https://night-shift-5zvig7nbvq-ew.a.run.app/stage>. This page has the YouTube player's
   own controls, so the video can be dragged to a moment; the main page's video can't be dragged.
   Tap Football and wait until the bar under the video reads "next line 5:15". That means the goal's
   line is written and held for its moment.
2. **Main page**, <https://night-shift-5zvig7nbvq-ew.a.run.app>. Start Spain v England at least two
   minutes before going on, so the Lines card has lines to fix. Mute this tab: only Stage speaks.
3. **Mubit's console**, signed in, showing the requests for our task.

Check `/health` says ok. Read the proof panel's numbers and the adapter's state, so the spoken ones
match the screen.

## The script

Times are cumulative. *Italics* are what's on screen; the quoted text is spoken.

### 1. The promise (0:00–0:15)

*Main page, the six matches.*

"Tonight thousands of matches will be played that nobody calls. Fans get a ticker, or silence.
Touchline gives every match a commentator."

### 2. The goal, the peak (0:15–0:50)

*Stage tab, Spain v England, the 2023 Women's World Cup final. Drag the video to 5:05; Olga Carmona's
goal plays at 5:15.*

"The Women's World Cup final. Touchline reads the real match data and calls each moment when it
reaches the picture."

*Stop talking. Let the goal be called aloud, with the subtitle.*

"That line was written from the real match data and held until the goal reached the picture."

### 3. Another sport, same commentator (0:50–1:15)

*Stage tab, tap Cricket: India v Pakistan, 2022 T20 World Cup. When the bar shows "next line 13:23",
drag to 13:15. Kohli's six off Haris Rauf plays at 13:23, called by Raju.*

"Same commentator, same prompt, different sport, and a cricket voice."

### 4. The fix (1:15–1:35)

*Main page tab. Open the Lines card, tap Fix on a line, type the correction, send. The line shows
Fixed and the proof panel's fix count goes up by one.*

"Say a line is wrong. A producer fixes it in one tap. The fix is kept beside the original, and it
goes back through Mubit to train our own commentator."

### 5. The proof (1:35–1:55)

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
  not our product: it holds those calls, the data our own commentator trains on. Our own commentator isn't trained
  yet, so we won't show you a number we don't have."

### 6. Close (1:55–2:00)

"Every match deserves a commentator. Now every match can have one."

## Rehearsal

Rehearse once on the deployed URL before recording, then note here the date, the commit deployed on
main and the total time. Check in particular:

- dragging the Stage video before a moment still calls that moment when the picture reaches it;
- the voice changes when the sport changes;
- a fix shows as Fixed and the proof panel's fix count goes up by one.
