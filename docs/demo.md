# The demo

**The promise: every match gets a commentator.** The peak is a goal called live, aloud, over the
broadcast picture. The script is about 2 minutes 40 seconds spoken; the limit is 3.

Everything runs from main's deployed URL, <https://night-shift-5zvig7nbvq-ew.a.run.app>, with the
sound on. Anything shown outside our product, such as Mubit's console, is said aloud as such.

## Before going on

- Open the live URL in a fresh tab, sound on, and check `/health` says ok.
- Note the proof panel's numbers, so the spoken ones match the screen.
- Check the adapter's state on the proof panel, and pick the matching line in step 5.
- Have one wrong line in mind to fix, or use the wording given in step 3.

## The script

Times are cumulative. *Italics* are what's on screen; the quoted text is spoken.

### 1. The promise (0:00–0:20)

*The home page: the six matches.*

"Tonight thousands of matches will be played that nobody calls. The women's league, the county chase,
the Sunday league final. Fans get a ticker, or silence. Touchline gives every match a commentator."

### 2. The live call, the peak (0:20–1:05)

*Tap Spain v England, the 2023 Women's World Cup final. Drag the video timeline to about 5:00; Olga
Carmona's goal plays at 5:15.*

"This is the Women's World Cup final. Touchline is reading the real match data and calling each
moment as it reaches the picture."

*Stop talking. Let the goal play and be called aloud, in the British voice, with the subtitle.*

*After the call:* "That line didn't exist a second ago. It was written and spoken as the goal went in."

### 3. The fix (1:05–1:30)

*Open the Lines card, tap Fix on a line, type the correction, send. The line shows Fixed.*

"Say a line is wrong. A producer fixes it in one tap. The fix is kept beside the original, and it
goes back to train the commentator."

If no line is wrong, correct the goal call to: "Olga Carmona, low across Mary Earps! Spain lead the
World Cup final!"

### 4. Every sport, one commentator (1:30–2:10)

*Tap India v Pakistan, 2022 T20 World Cup. The voice changes to the Indian commentator. Drag the
timeline to about 13:10; Kohli's first six off Haris Rauf plays at 13:23.*

"Same commentator, different sport. This is Kohli against Pakistan, called in an Indian voice."

*Let the six be called. Back to the home page.*

"And the same commentator, with the same prompt, calls the 2022 World Cup final, Jordan's last shot,
Kobe's 81 and Hamilton at Silverstone."

### 5. The proof (2:10–2:40)

*The proof panel.*

"The first word lands in about half a second, and a line costs a fraction of a cent." Read both
numbers off the panel.

The one line on the tech: "Every call goes through Mubit, which trains a smaller commentator of our
own on these calls and every producer fix."

Then one of these, matching the adapter's state on the panel:

- **Adapter ready:** "Here's our trained commentator, scored against the big model on matches it
  never saw." Read the agreement off the panel as it is shown, and claim nothing beyond it.
- **Adapter not ready (the fallback):** "Our own commentator is still training on Mubit. When it
  lands, this panel scores it against the big model on matches it never saw. We'll show you that
  number, not promise it."

### 6. Close (2:40)

"Every match deserves a commentator. Now every match can have one."

## Rehearsal

Rehearse once on the deployed URL before recording, then note here the date, the commit deployed on
main and the total time. Check in particular:

- dragging the timeline before a moment still calls that moment when the picture reaches it;
- the voice changes when the sport changes;
- a fix shows as Fixed and the proof panel's fix count goes up by one.
