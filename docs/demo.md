# The demo

**The promise: every match gets a commentator.** The peak is a goal called aloud over the broadcast
picture. The script runs two minutes.

Everything runs from main's deployed URL, with the sound on. Anything shown outside our product, such
as Mubit's console, is said aloud as such.

## Before going on

Open four tabs:

1. **Stage, football**, <https://night-shift-5zvig7nbvq-ew.a.run.app/stage>. This page has the YouTube
   player's own controls, so the video can be dragged to a moment; the main page's video can't be
   dragged. Tap Football and wait until the bar under the video reads "15 held" (about 20 seconds):
   every line is written and waiting for its moment. Then pause the video with its own controls.
   While it is paused, the commentary waits.
2. **Stage, cricket**: the same page in a second tab. Tap Cricket, wait for "32 held", then pause.
   Each tab runs its own replay, so neither has to load during the demo.
3. **Main page**, <https://night-shift-5zvig7nbvq-ew.a.run.app>. Tap the Spain v England tile at least
   two minutes before going on, so the Lines card has lines to fix. Mute this tab: only Stage speaks.
4. **Mubit's console**, signed in, showing the requests for our task.

Check `/health` says ok. Read the proof panel's numbers and the adapter's state, so the spoken ones
match the screen.

**If the highlights can't play** (the page says "Highlights can't play here", or /stage says "Video
unavailable"), /stage shows lines as they arrive, without waiting for a moment, so it can't carry
the peak. Use the main page for the goal instead: it keeps the commentary on the replay clock without
the picture. Its replay starts at about 1:37, so tap the Spain v England tile about 3 minutes 40
seconds before step 2, and the goal is called at 5:15.

## The script

Times are cumulative. *Italics* are what's on screen; the quoted text is spoken.

### 1. The promise (0:00–0:15)

*Main page, the wall of six matches.*

"Tonight thousands of matches will be played that nobody calls. Fans get a ticker, or silence.
Touchline gives every match a commentator."

### 2. The goal, the peak (0:15–0:50)

*Stage football tab, Spain v England, the 2023 Women's World Cup final. Drag the paused video to
5:05 and press play. The bar reads "next line 5:15"; Olga Carmona's goal plays at 5:15.*

"The Women's World Cup final. Touchline reads the real match data and calls each moment when it
reaches the picture."

*Stop talking. Let the goal be called aloud, with the subtitle.*

"That line was written from the real match data and held until the goal reached the picture."

### 3. Another sport, same commentator (0:50–1:15)

*Stage cricket tab, India v Pakistan, 2022 T20 World Cup. Drag the paused video to 13:15 and press
play. Kohli's six off Haris Rauf plays at 13:23, called by Raju.*

"Same commentator, same prompt, different sport, and a cricket voice."

### 4. The fix (1:15–1:35)

*Main page tab. In the Lines card, tap Fix on a line. The sheet shows what Touchline said, with the
line ready to correct. Type the correction and send. The line shows Fixed and the proof panel's fix
count goes up by one.*

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

### Headless check, 2026-10-24 about 00:10 UTC

Each step was checked on the deployed URL (main at 42f73cc) in headless Chrome on our build server.
This is not the timed rehearsal, which still needs a person.

- **YouTube refused to play in headless Chrome** (error 150, or "Highlights can't play here"). YouTube
  lists all six videos as embeddable, so this is most likely the headless browser on a cloud server.
  Confirm playback on the demo laptop.
- **/stage, with a stand-in for the player's clock:** the goal was called at 5:15 and Kohli's six at
  13:23, each with its audio playing. Football held all 15 lines within 20 seconds of the tap.
- **Main page:** a tile opens the full-screen match, and the replay clock carries the commentary
  without the video. Fix opens the sheet (it was not sent, to keep test fixes out of the training
  data). The proof panel reads "Not trained yet" for the adapter.
