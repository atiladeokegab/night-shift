# The commentator's voice

## Model

Lines are spoken by ElevenLabs **`eleven_v3`**, its most expressive model. It reads audio tags such as `[shouting]`, which `eleven_flash_v2_5` would read out loud as words.

| Moment | Tag |
|---|---|
| Goal, wicket, six, last ball | `[shouting]` |
| Shot saved or missed, four, card | `[excited]` |
| Chase build-up | `[hushed]` |
| F1: lead change, red flag (a crash), chequered flag | `[shouting]` |
| F1: lights out, other overtakes, pit stop, safety car | `[excited]` |
| F1 build-up: low grip, last lap | `[hushed]` |
| Anything else (substitution, injury) | none |

The tag goes into the text sent to ElevenLabs and nowhere else. The stored line, the page and Mubit only ever see the line as the commentator wrote it.

## On time

A v3 request takes 2-3 s warm and 11-15 s cold. Lines for a video-mapped match are created well ahead of the picture, so the server starts each line's audio as soon as the line exists and keeps it in memory. The page's `GET /lines/{id}/audio` then serves audio that is already made.

1. Try `eleven_v3` with the moment's tag. A line made before its moment gets one v3 call of at least 7 s, even if that runs past the moment: a v3 line a little late beats a flat one on time. A line spoken as it arrives may retry v3 once, as long as it can still finish 1.5 s before the moment.
2. Otherwise use `eleven_flash_v2_5` without the tag (about 0.3 s warm).
3. If that also fails, the route answers 503 and the page falls back to browser speech.

A line's moment is due at the replay's start plus its `video_t`, less the video's start, which is 10 s before its first mapped moment so the first line has time for v3. A line with no video time is spoken as soon as it arrives, so v3 gets 4 s. At most 3 requests run at once.

Measured on 2026-10-23 on Kohli v Pakistan (32 lines, first 12 fetched): all 12 were voiced by v3, and each was ready before its video time. The first was ready at 1.6 s for a moment at 9 s.

Run `uv run python -m core.voice` before the demo. It speaks one line in every voice, the sport picks included, on both models and any `VOICE_MODEL_<SPORT>`, so no demo line pays for a cold start. It reads the `VOICE_*` settings from the environment, and from `.env` for any the environment leaves unset; nothing else is read from `.env`, so `ELEVENLABS_API_KEY` must be in the environment. Nothing runs it at service start or deploy.

## Voices

The lead picked these on 2026-10-23, after the listening test below: Raju, Cricket Match Commentator, for cricket and the British Football Announcer for football, both on `eleven_v3`.

| Sport | The pick | On the page (`GET /voices`) | Set by | With no setting |
|---|---|---|---|---|
| Football | British Football Announcer (`gU0LNdkMOQCOrPrwtbee`) | `football-pick` | `VOICE_FOOTBALL` | `connor`, Connor: British, energetic |
| Cricket | Raju, Cricket Match Commentator (`IX4AgWzTnD6q0cNvHqvK`) | `cricket-pick` | `VOICE_CRICKET` | `viraj`, Viraj: Indian English, energetic |
| Basketball | Sam, Engaging Game Narrator | `sam` | the code default | `sam` |
| F1 | British Football Announcer | `announcer` | the code default | `announcer` (`VOICE_F1` changes it) |
| Any (page setting) | | `george`, George: British, warm | | |

Football's pick is the same ElevenLabs voice as F1's `announcer`, so it gets its own `football-pick` entry: `GET /voices` names one sport per voice, and the page needs a default for each.

## Changing the pick (config, not code)

The lead picks the final voice and model per sport from the listening test. The pick goes in the environment:

```bash
VOICE_FOOTBALL=gU0LNdkMOQCOrPrwtbee   # an id from GET /voices, or any ElevenLabs voice id
VOICE_CRICKET=IX4AgWzTnD6q0cNvHqvK
VOICE_MODEL_FOOTBALL=eleven_v3        # or eleven_flash_v2_5: no tags, fastest
VOICE_MODEL_CRICKET=eleven_v3
VOICE_LABEL_FOOTBALL="British Football Announcer"   # the name the page shows
VOICE_LABEL_CRICKET="Raju, Cricket Commentator"
```

Empty or unset means the default. A raw ElevenLabs voice id shows in `GET /voices` as `football-pick` (or `cricket-pick`), with the sport's default `lang`. The id itself stays on the server. Library voices work by id without being added to the account, but each one's first request is cold, so run `uv run python -m core.voice` after changing the pick. `GET /voices` reports the chosen default for each sport. The key stays in `ELEVENLABS_API_KEY` on the server, and the browser never calls ElevenLabs.

## Candidates compared

The listening test, on 2026-10-23, compared these 10 voices on `eleven_v3` with audio tags against today's `eleven_flash_v2_5`. No audio is committed. The tags tried were `[shouting]`, `[screaming]`, `[excited]`, `[whispers]`, `[hushed]`, `[breathless]`, `[gasps]` and `[laughs]`.

| Sport | Voice | ElevenLabs voice id | Accent | Source |
|---|---|---|---|---|
| Football | Connor | `xtw8E1CXDMtNKx4sgP7u` | en-GB | in account (today's default) |
| Football | British Football Announcer | `gU0LNdkMOQCOrPrwtbee` | en-GB | library |
| Football | Sam, Engaging Game Narrator | `gnPxliFHTp6OK6tcoA6i` | en-US | library |
| Football | Daniel | `onwK4e9ZLuTAKqWW03F9` | en-GB | premade |
| Football | Raju, High Energy Football Commentary | `jAUbTDuEGvdxrWhSe9eR` | en-IN | library |
| Cricket | Viraj | `PdJQAOWyIMAQwD7gQcSc` | en-IN | in account (today's default) |
| Cricket | Shaurya M, Dynamic Cricket Commentator | `fRV3NpXPa1DGVnFs6Dg5` | en-IN | library |
| Cricket | Raju, Cricket Match Commentator | `IX4AgWzTnD6q0cNvHqvK` | en-IN | library |
| Cricket | Chris, Sports Commentator | `Anr9GtYh2VRXxiPplzxM` | en-IN | library |
| Cricket | Pavan M, Energetic Sports Commentator | `BbDDnkbyQUUuTAZbQNEu` | en-IN | library |

The pick: the British Football Announcer for football and Raju, Cricket Match Commentator, for cricket, both on `eleven_v3` (see Voices above).
