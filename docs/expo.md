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
   **Review** in the top nav. Find Cahill's card, Chelsea v Tottenham Hotspur · 57:41; it is the one whose
   line says "one-all". Then **Fix this line**: enter the **Producer token**, type exactly
   `Gary Cahill scores! Chelsea pull one back, but Tottenham still lead two to one.`, and press **Send fix**.
   In a new tab, open <https://night-shift-5zvig7nbvq-ew.a.run.app/?match=3754092&at=26>: the replay says
   that moment in the fixed words, tagged **Fixed by producer**. Every later line of the match is called
   with that match's fixes, at most five, in its request.
4. **The training receipt.** Back on the Review tab, the panel under the fix reads **Sent to training**,
   then:
   - **Fix saved: request** with its Mubit request id;
   - a **Score check example** row for each example sent (**Line as said**, **Fixed text**);
   - **Score check examples: N → M**;
   - **Training run pending**, or **Latest Score check adapter: v**N once a version is recorded.

   Say "the count went up", not by how much: an example sent before is skipped.
5. **Mubit's console.** Open it beforehand, signed in, and say it is Mubit's page, not ours: the
   **Adapters** page, the **Score check** card ("Check one line of…"). As read at 00:14 UTC on 25 Oct:
   v1 at 33.3% on 12 test cases against a 95% target, "Not ready yet". Say "the first Score check
   version scored 33.3% against a 95% target; every fix is training for the next one". Read the card
   again on the day.

**Fallback:** if live is off air ("Commentator is off air for today", the $20 daily budget), or past 10 new
replays an hour ("You've started a lot of replays"), the site replays stored lines with no new calls,
so play the MP4 of the film instead.
