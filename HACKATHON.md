# Night Shift: Mubit Hackathon, London

Touchline: the describer that checks itself. It describes matches aloud for blind and low-vision fans, for the matches a platform streams with nobody describing them. An agent with tools turns a real match event feed into one spoken line per key moment, with the first word of text in about 0.5 s (median), and checks the score and key numbers in each line against the data before air; producers fix wrong lines, and every call and fix goes through Mubit as training, not serving: the console (25 Oct, 00:14 UTC) shows 11 tasks, 8 adapters and 0 serving, the first Score check version at 33.3% and the best commentary task at 58.3% against a 95% target, none ready, and the app does not call an adapter. Track: Recurring tasks. Score check is the recurring task: does this line's score match the match data? The number check answers it in code for every lead line on every match before air, and every producer's fix goes to Score check's training on Mubit as a labelled example. Training, not serving.

Official rules: https://luma.com/nightshift-london

Smoke: `make smoke`

The product that ships is `main`: the last commit that passed the smoke check.

Board: https://github.com/users/atiladeokegab/projects/13

## Deadlines

Your agent checks these every session against the UTC column. GitHub milestones keep only the
date, so this UTC column is the clock, never the milestone.

| Deadline | Event time | UTC |
|---|---|---|
| spine | 2026-10-23T23:00+01:00 | 2026-10-23T22:00Z |
| code freeze | 2026-10-25T09:00+00:00 | 2026-10-25T09:00Z |
| submit | Once submissions open: submit with `/submit`; final time in #announcements | Not fixed; our internal freeze is 09:00 UK |

## Judging criteria

- Use of Mubit: a correction turning into a model update, live
- Usefulness: a real recurring task someone would want handled
- Technical execution: it works and holds up under questions
- Demo: clear, live, under the time limit

## Team

| Name | GitHub | Role | Bring |
|---|---|---|---|
| Atilade | @atiladeokegab | lead, designer, electronic engineering, IBM Z/COBOL, AI agents, product |  |
| Persia | @PersiaF04 | full stack engineer |  |
