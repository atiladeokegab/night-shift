# Night Shift: Mubit Hackathon, London

Touchline: the describer that checks itself, for the matches a platform streams with nobody describing them. An agent with tools turns a real match event feed into one spoken line per key moment, with the first word of text in about 0.5 s (median); producers fix wrong lines, every call and fix goes through Mubit, and Mubit trains a small commentator model on the recorded calls: 6 versions trained, none has passed Mubit's test yet (best 55.8%), and the app does not call an adapter. Track: Own your intelligence layer.

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
| submit | 2026-10-25T10:00+00:00 | 2026-10-25T10:00Z |

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
