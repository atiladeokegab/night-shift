# Live demo (expo)

On the live site, <https://night-shift-5zvig7nbvq-ew.a.run.app>, with the sound on, in the film's order.
Read every figure off the screen at the time; the one written here (step 5) is dated.

1. **A match described.** Open <https://night-shift-5zvig7nbvq-ew.a.run.app/?match=3913122>: Brighton &
   Hove Albion WFC v Bristol City WFC plays, ON AIR, and is described aloud. Press **E** (**Close your
   eyes**): the picture is covered, the line and the score stay, the voice carries on.
2. **The Proof card.** On the same page, the **Proof** tab: **Calls · This match** and **Calls · All
   matches** (**First time**, **Auto-fixed**, **To a human**), then **Per full replay** (**Total**,
   **Model**, **Voice**).
3. **A producer's fix.** This step needs the producer token, so have it ready but never on screen.
   **Review** in the top nav. Don't fix Cahill's "level it at one-all" line again: a fixed mistake leaves
   the queue, and each Score check example is sent only once, so the count would not move. Fix a fresh
   lead line instead, from any match but Brighton & Hove Albion WFC v Bristol City WFC or the São Paulo
   Grand Prix: those two are held out of training (`HELD_OUT` in
   [`eval/linecheck.py`](../eval/linecheck.py)). At 05:15 UTC on 25 Oct the queue held, for one, the card
   Chelsea v Tottenham Hotspur · 57:41, "Gary Cahill with the half volley! Chelsea are back in it, but
   Tottenham lead one-nil— two-one!". **Fix this line**: enter the **Producer token**, type
   `Gary Cahill with the half volley! Chelsea are back in it, but Tottenham still lead two-one.` (it
   passes the number check), and press **Send fix**. In a new tab, open
   <https://night-shift-5zvig7nbvq-ew.a.run.app/?match=3754092&at=26>: the replay says that moment in the producer's words, tagged
   **Fixed by producer**. Every later line of the match is called with that match's fixes, at most
   five, in its request.

   If the queue has no fresh card, or the fix is refused, show the fix already made instead: on Review,
   **Corrections sent to Mubit** lists Cahill's two Score check rows from 23:45 UTC on 24 Oct, each with
   its session and request.
4. **The training receipt.** Back on the Review tab, the panel under the fix reads **Sent to training**,
   then:
   - **Fix saved: request** with its Mubit request id;
   - a **Score check example** row for each example sent (**Line as said**, **Fixed text**);
   - **Score check examples: N → M**;
   - **Training run pending**, or **Latest Score check adapter: v**N once a version is recorded.

   Say "the count went up" only if M is more than N. If the panel reads "No new Score check example",
   say that: each was already sent, or the data can't label it.
5. **Mubit's console.** Open it beforehand, signed in, and say it is Mubit's page, not ours: the
   **Adapters** page, the "Check one line of 2" card.
   Earlier, at 00:14 UTC on 25 Oct, the Score check card ("Check one line of…") showed v1 at 33.3% on
   12 test cases against a 95% target, "Not ready yet". Say: Mubit's "Check one line of 2" task (one of our two line-checking tasks; the console cuts the name short) shows 94.6% for its first version, testing v1, in testing (console read by hand, 25 Oct 2026 06:27 UTC). The app does not call an adapter. Read the card
   again on the day.

**Fallback:** if live is off air ("Commentator is off air for today", the live deploy's `DAILY_BUDGET_USD` of $20; the code's default
is $50), or past 10 new
replays an hour ("You've started a lot of replays"), the site replays stored lines with no new calls,
so play the MP4 of the film instead.
