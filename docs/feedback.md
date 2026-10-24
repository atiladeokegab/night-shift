# Check-in #2: what the judge asked and where it landed

The judge's second check-in (24 October 2026) made the points below. Each row says what we did and
where to check it: a pull request, a commit, or a file and line on `integration`. **Open PR** means
the work is in review and not merged yet. **Not yet** means it isn't done.

| The point | What we did | Evidence |
|---|---|---|
| Don't plan around a fixed 10:00 UTC; submit once submissions open | A docs change: submit with /submit as soon as submissions open, not at a fixed time | Open PR: #491 |
| Pick the one demo moment that matters most: a producer's fix on a Brighton v Bristol City line changing a later line on that match | A script that sends a producer's fix and then reads the later lines on that match that carry it | Not yet: on branch `fix-then-later`, no PR yet |
| Make sure the code shows the Mubit calls | The README names each place Mubit is called, by function, file and line, and a test keeps each link on its call | #490; [README "Where Mubit is called"](../README.md#where-mubit-is-called); [`tests/test_readme_numbers.py:79`](../tests/test_readme_numbers.py#L79) |
| Show a correction made in Mubit's console changing a later answer on the same task | Producer fixes are sent to training. A script sends the same Score check request (a stored Chelsea v Spurs line with a wrong score) before and after a Score check version is set to serve, and saves each answer with its Mubit request id to `eval/scorecheck_before_after_*` | Open PR: #489 |
| Make it obvious why a fan comes back every match day | A line at the top of the README says why, for a blind or low-vision fan whose team's match has no described broadcast | #490; [README.md:20](../README.md#L20) |
| Feedback from a screen-reader user | None collected yet | Not yet |
| Keyboard and screen-reader support traced to code | Each keyboard and screen-reader claim, with the code that does it and its test, or marked not tested | #492; [README.md:78](../README.md#L78); [evidence: Keyboard and screen reader](evidence.md#keyboard-and-screen-reader) |
| The live figures in the README traced to code | The README's numbers are generated from the eval output and the saved `/stats` read, and a test fails if they drift | #472 (`e05efae`); [`tests/test_readme_numbers.py`](../tests/test_readme_numbers.py) |
| Handle the plain-env `PRODUCER_TOKEN` | Deploy mounts `PRODUCER_TOKEN` from Secret Manager, not as a plain environment variable | Open PR: #487 |
| A 2-minute demo uploaded as an MP4 or MOV (no YouTube links) | Plan: a 1:50 cut, to be recorded on the live URL | Not yet: plan in [`docs/demo.md`](demo.md) |
