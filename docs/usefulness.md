# Why Touchline is useful

Touchline's recurring job is to help a fan follow a match when they cannot see the action and no
described broadcast is available. Today it demonstrates that job on historical match replays:
spoken key moments, large captions, questions about the match so far, and a producer who can correct
a wrong line. A live sports-feed integration remains future work.

## Evidence that the job matters

These are primary sources checked on 25 October 2026. They describe other services and their users;
none of these organizations or people has endorsed, tested or bought Touchline.

| Evidence | What it establishes | Source |
|---|---|---|
| Manchester City publishes accounts from supporters Stuart Beckett and Fred Yeomans: described commentary helped Stuart return to matches, and Fred says it keeps him involved. The club also describes listening from home and supporter questions during games. | Named fans report participation and belonging, with a use that repeats each match. This is evidence for the user need, rather than feedback on our product. | [Manchester City: supporters' experience](https://www.mancity.com/news/club/level-playing-fields-audio-descriptive-commentary-26-feb-63749957) |
| ITV expanded its Guinness Six Nations audio-description trial from two matches in 2024 to four in 2025, with Guinness and RNIB. ITV reports a positive response to the trial. | A broadcaster and sponsor invested in extending a recurring service across another sport. No budget or willingness to pay for Touchline is disclosed. | [ITV announcement, 31 January 2025](https://www.itv.com/presscentre/media-releases/itv-and-guinness-extend-live-descriptive-audio-commentary-2025-guinness-six-nations) |
| Sky and Guinness support selected Premier League audio description, with RNIB input. | Established institutional support for the category. | [Sky's accessibility announcement](https://www.sky.com/watch/premier-league-accessibility) |
| FIFA announced free audio description at selected Club World Cup 2025 stadiums, following provision at the 2022 World Cup and 2023 Women's World Cup, and trained commentators for the role. | Governing bodies repeatedly provide this service; fan access need not depend on the fan paying directly. | [FIFA announcement, 29 May 2025](https://inside.fifa.com/organisation/news/audio-description-commentary-milestone-most-inclusive-club-tournament-ever) |
| Level Playing Field reports Wrexham's supporter association and local sponsors funded a £4,000 audio-description project including four years of management and maintenance, at no cost to the club. It describes returning and new supporters benefiting. | A concrete example of local funding and a supporter association helping deliver the service. This historical project is not a current supplier quote or a comparable software price. | [Level Playing Field: Wrexham](https://www.levelplayingfield.org.uk/news-item/audio-description-commentary-at-wrexham-afc/) |
| RNIB reports that EURO 2024 audio description could be accessed remotely, but lacking a video feed reduced its appeal for shared viewing. Its synthetic-speech research also identifies problems with emotional nuance and sound mixing. | Audio, shared viewing and voice quality all matter. Generating speech alone does not establish a good accessible experience. | [RNIB's 2024 accessible-media review](https://www.rnib.org.uk/news/rnibs-accessible-media-services-overview-2024/) |

This supports a focused opportunity: a club or streaming platform with an event feed and matches
without description could offer an additional way to follow them. It does not establish how many
such matches exist, the addressable market, or demand for an AI replacement for trained describers.

## What the current product contributes

| Recurring need | What Touchline does today | Inspect the implementation and checks |
|---|---|---|
| Follow the important action without watching the picture | Describes selected key moments aloud with captions over replayed highlights, across football, cricket, basketball and F1. It does not describe every pass, off-ball action or crowd reaction. | [Replay pipeline](../core/replay.py), [voice](../core/voice.py), [feed tests](../tests/test_feed.py) |
| Ask for the state of the match | Ask checks answers against available match context; the UI keeps Ask disabled at a video's cold open until a mapped event is visible. Direct API event-identity limitations remain tracked in [issue #520](https://github.com/atiladeokegab/night-shift/issues/520). | [Answer checks: `checked_answer`](../core/insight.py), [Ask tests](../tests/test_ask_check.py), [cold-open regression](../web/e2e/cold-open-ask.spec.ts) |
| Reach controls and understand the spoken result | Keyboard controls, captions and screen-reader announcements have automated checks. These are engineering checks; no direct screen-reader user study has been collected. | [Keyboard tests](../web/e2e/keyboard.spec.ts), [accessibility tests](../web/e2e/a11y.spec.ts), [caption announcements](../web/src/components/Caption.tsx), [accessibility evidence](evidence.md#keyboard-and-screen-reader) |
| Reduce wrong calls reaching the listener | The number check retries a rejected line once, then uses a line built from event data. Producers can correct remaining errors. The check misses some factual errors; its measured limits are public. | [Checker: `wrong_numbers`, `checked`](../core/insight.py), [fallback tests](../tests/test_fallback.py), [producer-fix tests](../tests/test_core_fix.py), [measured results](../README.md#how-well-the-check-works) |
| Keep repeat viewing affordable | Stored lines can be replayed without another commentary model call; concurrency and spending limits bound new generation. | [Cache and budget guard](../core/guard.py), [cache tests](../tests/test_cached_first.py), [guard tests](../tests/test_guard.py) |

The recurring operator workflow is to load a supported match feed, make its commentary available,
review flagged lines, and carry producer corrections into later requests and training. Today the
match library and replay pipeline demonstrate that workflow. Serving new live fixtures, reliable
multi-instance operation, and a distribution agreement with a rights holder remain unproven.

## Buyer and cost: a testable proposition

The candidate buyer is a club's media or accessibility team, a streaming platform, or an
accessibility sponsor. The proposed purchase is match coverage for their fans; the evidence above
shows those kinds of organizations already support description. No organization has agreed to
pay us, and we have not set a price.

Our [saved statistics](../eval/live_stats_2026-10-25.json) report about **$0.41 per highlights replay
over 133 replays**, including voice ([measurement explanation](evidence.md#the-problem)). That is a
measured operating cost on this demo workload. It is not a full-match cost, a commercial price,
a profit margin or a saving against a human describer. Feed licensing, rights, hosting, support
and producer review would also enter a commercial cost model.

## What would prove usefulness beyond the prototype

The published sources establish the need. The next evidence must come from our own users and a
prospective buyer. Neither has been collected yet:

1. With blind and low-vision fans, compare the same replay with their existing way of following it
   and with Touchline. Record whether they can follow the score and key action, use the controls,
   tolerate the voice and delay, and choose to return. Include incorrect calls and recovery.
2. With a club or platform, confirm which fixtures lack description, whether a licensed event feed
   is available, who reviews errors, and who owns the accessibility budget. Seek a documented pilot
   commitment rather than infer demand from an industry-wide audience figure.
3. On that pilot workload, measure factual errors heard by fans, moment-to-audio delay, producer
   minutes per match, and total cost. Agree acceptable quality with users and the operator before
   claiming the system is ready for unsupervised coverage.

The strongest claim we can support today is specific: **described sport solves a recurring access
problem, real organizations fund it, and Touchline demonstrates a checked, correctable replay
workflow for that problem.** User preference, commercial demand and safe live operation still
need direct evidence.
