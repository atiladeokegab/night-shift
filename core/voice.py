"""The commentator's voice: each stored line read aloud by ElevenLabs, made when the line is created
so it is ready before the video reaches its moment. eleven_v3 with an audio tag for the moment's
kind; one retry, then eleven_flash_v2_5; with no key or every attempt failed the route answers 503
and the page uses browser speech instead. The key stays on the server."""

import asyncio
import logging
import os
import sys
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

log = logging.getLogger("night_shift.voice")

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
MODEL = "eleven_v3"  # VOICE_MODEL_<SPORT> overrides it per sport
FALLBACK_MODEL = "eleven_flash_v2_5"  # no audio tags: it would read "[shouting]" aloud
V3_TIMEOUT_S = 20.0  # v3 takes 2-3 s warm, 11-15 s on a cold first request
FALLBACK_TIMEOUT_S = 10.0
FALLBACK_RESERVE_S = 1.5  # v3 stops this long before the moment, so flash still lands in time
LIVE_BUDGET_S = 4.0  # a line with no video time is spoken as it arrives
CONCURRENCY = 3  # a whole match's lines arrive in seconds; ElevenLabs caps concurrent requests

# The page's voice setting. ids are ours; eleven_id never leaves the server. VOICE_<SPORT> takes an
# id here or any ElevenLabs voice id (all_voices) as the sport's default: the lead's pick from
# docs/voice.md is config, not code. Viraj and Connor are ElevenLabs library voices: the first
# call on each is slow (13-16 s measured 2026-10-23), so run `uv run python -m core.voice`
# before the demo.
VOICES = [
    {
        "id": "viraj",
        "lang": "en-IN",
        "label": "Viraj: Indian English, energetic",
        "default_for": "cricket",
        "eleven_id": "PdJQAOWyIMAQwD7gQcSc",
    },
    {
        "id": "connor",
        "lang": "en-GB",
        "label": "Connor: British, energetic",
        "default_for": "football",
        "eleven_id": "xtw8E1CXDMtNKx4sgP7u",
    },
    {
        "id": "george",
        "lang": "en-GB",
        "label": "George: British, warm",
        "default_for": None,
        "eleven_id": "JBFqnCBsd6RMkjVDRZzb",
    },
    {
        "id": "sam",
        "lang": "en-US",
        "label": "Sam: American, play-by-play",
        "default_for": "basketball",
        "eleven_id": "gnPxliFHTp6OK6tcoA6i",
    },
]

# A moment's kind to the eleven_v3 audio tag it is read with; anything else is read plainly.
TAGS = {
    "Wicket": "[shouting]",
    "Six": "[shouting]",
    "Last ball": "[shouting]",
    "Shot": "[excited]",
    "Four": "[excited]",
    "Foul Committed": "[excited]",
    "Bad Behaviour": "[excited]",
    "Chase": "[hushed]",
    "End of game": "[shouting]",
    "Steal": "[excited]",
    "Free throw": "[excited]",
}


def _big_basket(m: dict) -> bool:
    """Basketball: a lead change, or a three, a dunk or any field goal in the last two minutes."""
    if m.get("sport") != "basketball":
        return False
    detail = m.get("detail") or {}
    closing = (m.get("period") or 0) >= 4 and str(m.get("clock", "99:99")) <= "02:00"
    field_goal = m.get("type") == "Field goal"
    dunk = "DUNK" in str(detail.get("play", "")).upper()
    return bool(detail.get("lead_change")) or (
        field_goal and (closing or dunk or m.get("outcome") == "3 points")
    )


def tag_for(moment: dict) -> str | None:
    if moment.get("outcome") == "Goal" or _big_basket(moment):
        return "[shouting]"
    return TAGS.get(moment.get("type"))


def all_voices(env=os.environ) -> list[dict]:
    """VOICES, plus `<sport>-pick` for each VOICE_<SPORT> set to a raw ElevenLabs voice id."""
    picks = []
    for v in VOICES:
        sport = v["default_for"]
        chosen = env.get(f"VOICE_{sport.upper()}") if sport else None
        if chosen and all(chosen not in (x["id"], x["eleven_id"]) for x in VOICES):
            label = f"{sport.title()} pick"
            picks.append({**v, "id": f"{sport}-pick", "label": label, "eleven_id": chosen})
    return VOICES + picks


def default_voice(sport: str | None, env=os.environ) -> dict:
    chosen = env.get(f"VOICE_{str(sport).upper()}")
    return next((v for v in all_voices(env) if chosen in (v["id"], v["eleven_id"])), None) or next(
        (v for v in VOICES if v["default_for"] == sport), VOICES[0]
    )


def model_for(sport: str | None, env=os.environ) -> str:
    return env.get(f"VOICE_MODEL_{str(sport).upper()}") or MODEL  # empty in .env means unset


class Speaker:
    """Each line's audio per voice, made once and kept. The tag goes into the TTS text only, never
    into the stored line or anything sent to Mubit."""

    # shortcut: audio is kept in this process's memory (~50 KB a line); a bucket if a session
    # outgrows it or Cloud Run runs more than one instance.
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport
        self.jobs: dict[tuple[str, str], asyncio.Task] = {}
        self.tags: dict[str, str | None] = {}
        self.slots = asyncio.Semaphore(CONCURRENCY)

    def prepare(self, line: dict, moment: dict, deadline: float | None = None) -> None:
        """Start the line's audio in its sport's voice; `deadline` is when (time.monotonic) its
        moment plays, None to speak it as it arrives."""
        self.tags[line["line_id"]] = tag_for(moment)
        if os.environ.get("ELEVENLABS_API_KEY"):
            self._job(line, default_voice(line.get("sport")), deadline)

    async def audio(self, line: dict, voice: dict) -> tuple[bytes, str] | None:
        made = await asyncio.shield(self._job(line, voice, None))
        if made is None:  # the next request tries again
            self.jobs.pop((line["line_id"], voice["id"]), None)
        return made

    def _job(self, line: dict, voice: dict, deadline: float | None) -> asyncio.Task:
        key = (line["line_id"], voice["id"])
        if key not in self.jobs:
            self.jobs[key] = asyncio.create_task(self._make(line, voice, deadline))
        return self.jobs[key]

    async def _make(self, line: dict, voice: dict, deadline: float | None):
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            return None
        end = deadline if deadline is not None else time.monotonic() + LIVE_BUDGET_S
        model = model_for(line.get("sport"))
        tag = self.tags.get(line["line_id"]) if "v3" in model else None
        text = f"{tag} {line['text']}" if tag else line["text"]
        async with httpx.AsyncClient(transport=self.transport) as client:
            if model != FALLBACK_MODEL:
                for _ in range(2):  # a cold first request can time out; the retry is warm
                    until = min(end - FALLBACK_RESERVE_S, time.monotonic() + V3_TIMEOUT_S)
                    audio = await self._tts(client, key, voice, model, text, until)
                    if audio:
                        return audio, model
            until = min(end, time.monotonic() + FALLBACK_TIMEOUT_S)
            audio = await self._tts(client, key, voice, FALLBACK_MODEL, line["text"], until)
            return (audio, FALLBACK_MODEL) if audio else None

    async def _tts(self, client, key, voice, model, text, until) -> bytes | None:
        async with self.slots:
            left = until - time.monotonic()
            if left <= 0:  # it would land after the moment
                return None
            try:
                # httpx's timeout is per read: only this bounds the request plus every chunk
                async with asyncio.timeout(left):
                    resp = await client.post(
                        TTS_URL.format(voice=voice["eleven_id"]),
                        params={"output_format": "mp3_44100_128"},
                        headers={"xi-api-key": key, "accept": "audio/mpeg"},
                        json={"text": text, "model_id": model},
                        timeout=left,
                    )
            except (httpx.HTTPError, TimeoutError) as exc:
                log.warning("voice %s failed: %s", model, type(exc).__name__)
                return None
        if resp.status_code != 200 or not resp.content:
            log.warning("voice %s answered %d", model, resp.status_code)
            return None
        return resp.content


def warm(key: str, transport: httpx.BaseTransport | None = None) -> dict[str, int | None]:
    """Speak one short line in every voice on both models; ms per voice, None if one failed."""
    took = {}
    with httpx.Client(transport=transport, timeout=30) as client:
        for v in all_voices():
            started = time.perf_counter()
            ok = True
            for model in (MODEL, FALLBACK_MODEL):
                try:
                    resp = client.post(
                        TTS_URL.format(voice=v["eleven_id"]),
                        params={"output_format": "mp3_44100_128"},
                        headers={"xi-api-key": key, "accept": "audio/mpeg"},
                        json={"text": "And we're live.", "model_id": model},
                    )
                    ok = ok and resp.status_code == 200 and bool(resp.content)
                except httpx.HTTPError:
                    ok = False
            took[v["id"]] = round((time.perf_counter() - started) * 1000) if ok else None
    return took


def voice_router(store, speaker: Speaker) -> APIRouter:
    router = APIRouter()

    @router.get("/voices")
    def voices():
        sports = sorted({v["default_for"] for v in VOICES if v["default_for"]}, reverse=True)
        default = {default_voice(s)["id"]: s for s in sports}  # one sport per voice
        return [
            {**{k: v[k] for k in ("id", "label", "lang")}, "default_for": default.get(v["id"])}
            for v in all_voices()
        ]

    @router.get("/lines/{line_id}/audio")
    async def line_audio(line_id: str, voice: str | None = None):
        # only stored lines are spoken, so the key can't be used to read out arbitrary text
        line = next((ln for ln in store.all("lines") if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        if voice:
            chosen = next((v for v in all_voices() if v["id"] == voice), None)
            if chosen is None:
                raise HTTPException(404, f"no voice {voice!r}")
        else:
            chosen = default_voice(line.get("sport"))
        if not os.environ.get("ELEVENLABS_API_KEY"):
            raise HTTPException(503, "voice not configured")
        started = time.perf_counter()
        made = await speaker.audio(line, chosen)
        if made is None:
            raise HTTPException(503, "voice upstream failed")
        audio, model = made
        ms = (time.perf_counter() - started) * 1000
        log.info("voice line=%s first_byte_ms=%d model=%s", line_id, ms, model)
        return Response(audio, media_type="audio/mpeg")

    return router


if __name__ == "__main__":
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    took = warm(key)
    for vid, ms in took.items():
        print(f"warm {vid}: {'FAILED' if ms is None else f'{ms} ms'}")
    sys.exit(1 if None in took.values() else 0)
