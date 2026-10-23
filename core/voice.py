"""The commentator's voice: a stored line read aloud by ElevenLabs streaming TTS. The key stays on
the server; with no key or an upstream failure the route answers 503 and the page uses browser
speech instead."""

import logging
import os
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

log = logging.getLogger("night_shift.voice")

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
MODEL = "eleven_flash_v2_5"
VOICE = "JBFqnCBsd6RMkjVDRZzb"  # George: warm British male, an ElevenLabs premade voice


def voice_router(store, transport: httpx.AsyncBaseTransport | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/lines/{line_id}/audio")
    async def line_audio(line_id: str):
        # only stored lines are spoken, so the key can't be used to read out arbitrary text
        line = next((ln for ln in store.all("lines") if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise HTTPException(503, "voice not configured")

        client = httpx.AsyncClient(transport=transport, timeout=10)
        started = time.perf_counter()
        try:
            upstream = await client.send(
                client.build_request(
                    "POST",
                    TTS_URL.format(voice=VOICE),
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
