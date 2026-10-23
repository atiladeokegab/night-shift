"""The commentator's voice: a stored line read aloud by ElevenLabs streaming TTS. The key stays on
the server; with no key or an upstream failure the route answers 503 and the page uses browser
speech instead."""

import logging
import os
import sys
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

log = logging.getLogger("night_shift.voice")

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
MODEL = "eleven_flash_v2_5"
# The page's voice setting. ids are ours; eleven_id never leaves the server. Viraj and Connor are
# ElevenLabs library voices: the first call on each took 13-16 s to first byte (measured
# 2026-10-23), ~0.15 s after. That cold call exceeds the 10 s timeout, answers 503 and the page
# falls back to browser speech, so run `uv run python -m core.voice` before the demo.
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
]


def warm(key: str, transport: httpx.BaseTransport | None = None) -> dict[str, int | None]:
    """Speak one short line in every voice; returns first-byte ms per voice, None if it failed."""
    took = {}
    with httpx.Client(transport=transport, timeout=30) as client:
        for v in VOICES:
            started = time.perf_counter()
            try:
                with client.stream(
                    "POST",
                    TTS_URL.format(voice=v["eleven_id"]),
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": key, "accept": "audio/mpeg"},
                    json={"text": "And we're live.", "model_id": MODEL},
                ) as resp:
                    ok = resp.status_code == 200 and next(resp.iter_bytes(), b"")
            except httpx.HTTPError:
                ok = False
            took[v["id"]] = round((time.perf_counter() - started) * 1000) if ok else None
    return took


def voice_router(store, transport: httpx.AsyncBaseTransport | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/voices")
    def voices():
        return [{k: v[k] for k in ("id", "label", "default_for", "lang")} for v in VOICES]

    @router.get("/lines/{line_id}/audio")
    async def line_audio(line_id: str, voice: str | None = None):
        # only stored lines are spoken, so the key can't be used to read out arbitrary text
        line = next((ln for ln in store.all("lines") if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        if voice:
            chosen = next((v for v in VOICES if v["id"] == voice), None)
            if chosen is None:
                raise HTTPException(404, f"no voice {voice!r}")
        else:
            sport = line.get("sport")
            chosen = next((v for v in VOICES if v["default_for"] == sport), VOICES[0])
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise HTTPException(503, "voice not configured")

        client = httpx.AsyncClient(transport=transport, timeout=10)
        started = time.perf_counter()
        try:
            upstream = await client.send(
                client.build_request(
                    "POST",
                    TTS_URL.format(voice=chosen["eleven_id"]),
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": key, "accept": "audio/mpeg"},
                    json={"text": line["text"], "model_id": MODEL},
                ),
                stream=True,
            )
            if upstream.status_code != 200:
                await upstream.aclose()
                raise HTTPException(503, f"voice upstream answered {upstream.status_code}")
            chunks = upstream.aiter_bytes()
            first = await anext(chunks, b"")
            if not first:
                await upstream.aclose()
                raise HTTPException(503, "voice upstream sent no audio")
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(503, f"voice upstream failed: {type(exc).__name__}") from exc
        except HTTPException:
            await client.aclose()
            raise
        log.info("voice line=%s first_byte_ms=%d", line_id, (time.perf_counter() - started) * 1000)

        async def body():
            try:
                yield first
                async for chunk in chunks:
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(body(), media_type="audio/mpeg")

    return router


if __name__ == "__main__":
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    took = warm(key)
    for vid, ms in took.items():
        print(f"warm {vid}: {'FAILED' if ms is None else f'{ms} ms'}")
    sys.exit(1 if None in took.values() else 0)
