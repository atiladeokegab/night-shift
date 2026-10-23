# The commentator's voice

## Model

Lines are spoken by ElevenLabs **`eleven_v3`**, its most expressive model. It reads audio tags such as `[shouting]`, which `eleven_flash_v2_5` would read out loud as words.

| Moment | Tag |
|---|---|
| Goal, wicket, six, last ball | `[shouting]` |
| Shot saved or missed, four, card | `[excited]` |
| Chase build-up | `[hushed]` |
| Anything else (substitution, injury) | none |

The tag goes into the text sent to ElevenLabs and nowhere else. The stored line, the page and Mubit only ever see the line as the commentator wrote it.

## On time

A v3 request takes 2-3 s warm and 11-15 s cold. Lines for a video-mapped match are created well ahead of the picture, so the server starts each line's audio as soon as the line exists and keeps it in memory. The page's `GET /lines/{id}/audio` then serves audio that is already made.

1. Try `eleven_v3` with the moment's tag. If it fails, retry it once, as long as it can still finish 1.5 s before the moment.
2. Otherwise use `eleven_flash_v2_5` without the tag (about 0.3 s warm).
3. If that also fails, the route answers 503 and the page falls back to browser speech.

A line's moment is due at the replay's start plus its `video_t`. A line with no video time is spoken as soon as it arrives, so v3 gets 4 s. At most 3 requests run at once.

Measured on 2026-10-23 on Kohli v Pakistan (32 lines, first 12 fetched): all 12 were voiced by v3, and each was ready before its video time. The first was ready at 1.6 s for a moment at 9 s.

Run `uv run python -m core.voice` before the demo. It speaks one line in every voice on both models, so no demo line pays for a cold start.

## Voices

| Sport | Default | ElevenLabs voice |
|---|---|---|
| Football | `connor` | Connor: British, energetic |
| Cricket | `viraj` | Viraj: Indian English, energetic |
| Any (page setting) | `george` | George: British, warm |

## Changing the pick (config, not code)

The lead picks the final voice and model per sport from the listening test. The pick goes in the environment:

```bash
VOICE_FOOTBALL=connor              # an id from GET /voices
VOICE_CRICKET=viraj
VOICE_MODEL_FOOTBALL=eleven_v3     # or eleven_flash_v2_5: no tags, fastest
VOICE_MODEL_CRICKET=eleven_v3
```

`GET /voices` reports the chosen default for each sport. The key stays in `ELEVENLABS_API_KEY` on the server, and the browser never calls ElevenLabs.

## Candidates compared

The listening test compared 10 voices on `eleven_v3` with audio tags against today's `eleven_flash_v2_5`. No audio is committed.
