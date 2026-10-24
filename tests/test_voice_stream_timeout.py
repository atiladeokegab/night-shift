"""The TTS deadline bounds its first chunk; later body reads use the stream timeout."""

import asyncio
import json
import time

import httpx

from core import voice
from core.voice import VOICES, Speaker

FIRST = b"AAAA"
SECOND = b"BBBB"
AUDIO = FIRST + SECOND


class LocalTTS:
    """A tiny HTTP/1.1 chunked TTS endpoint on localhost, using real HTTPX socket timeouts."""

    def __init__(self, *, first_delay=0.02, body_gate=None):
        self.first_delay = first_delay
        self.body_gate = body_gate
        self.first_sent = asyncio.Event()
        self.models = []
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/v1/text-to-speech/{{voice}}"

    async def close(self):
        self.server.close()
        await self.server.wait_closed()

    @staticmethod
    async def _chunk(writer, body):
        writer.write(f"{len(body):X}\r\n".encode() + body + b"\r\n")
        await writer.drain()

    async def _handle(self, reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                (
                    int(line.split(b":", 1)[1])
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                ),
                0,
            )
            payload = json.loads(await reader.readexactly(length))
            model = payload["model_id"]
            self.models.append(model)
            writer.write(
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
                b"Content-Type: audio/mpeg\r\nConnection: close\r\n\r\n"
            )
            await writer.drain()
            if model == voice.FALLBACK_MODEL:
                await self._chunk(writer, AUDIO)
            else:
                await asyncio.sleep(self.first_delay)
                await self._chunk(writer, FIRST)
                self.first_sent.set()
                if self.body_gate is not None:
                    await self.body_gate.wait()
                else:
                    await asyncio.sleep(0.8)
                await self._chunk(writer, SECOND)
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError):
            pass  # expected when a timeout closes a stalled response
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass


def _prepared(speaker, budget):
    line = {"line_id": "timeout-test", "sport": "football", "text": "Goal!"}
    deadline = time.monotonic() + voice.FALLBACK_RESERVE_S + budget
    speaker.prepare(line, {"type": "Goal"}, deadline)
    return line, deadline


def test_timed_first_chunk_allows_a_later_body_chunk_past_deadline(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "local-test-key")
    monkeypatch.delenv("VOICE_MODEL_FOOTBALL", raising=False)
    monkeypatch.setattr(voice, "V3_TIMEOUT_S", 1.5)
    monkeypatch.setattr(voice, "PREPARED_V3_S", 0.0)

    async def run():
        server = LocalTTS()
        monkeypatch.setattr(voice, "TTS_URL", await server.start())
        speaker = Speaker(httpx.AsyncHTTPTransport())
        try:
            line, deadline = _prepared(speaker, budget=0.5)
            clip = await speaker.stream(line, VOICES[1])
            assert clip.first_at < deadline - voice.FALLBACK_RESERVE_S
            await clip.ended.wait()
            assert clip.whole
            assert b"".join([part async for part in clip.follow()]) == AUDIO
            assert server.models == [voice.MODEL]
        finally:
            await server.close()

    asyncio.run(run())


def test_late_first_chunk_falls_back_to_flash(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "local-test-key")
    monkeypatch.delenv("VOICE_MODEL_FOOTBALL", raising=False)
    monkeypatch.setattr(voice, "PREPARED_V3_S", 0.0)

    async def run():
        server = LocalTTS(first_delay=0.45)
        monkeypatch.setattr(voice, "TTS_URL", await server.start())
        speaker = Speaker(httpx.AsyncHTTPTransport())
        try:
            line, _ = _prepared(speaker, budget=0.15)
            assert await speaker.audio(line, VOICES[1]) == (AUDIO, voice.FALLBACK_MODEL)
            assert server.models == [voice.MODEL, voice.FALLBACK_MODEL]
        finally:
            await server.close()

    asyncio.run(run())


def test_stalled_body_is_still_bounded_after_first_chunk(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "local-test-key")
    monkeypatch.delenv("VOICE_MODEL_FOOTBALL", raising=False)
    monkeypatch.setattr(voice, "V3_TIMEOUT_S", 0.45)
    monkeypatch.setattr(voice, "PREPARED_V3_S", 0.0)

    async def run():
        release_body = asyncio.Event()
        server = LocalTTS(body_gate=release_body)
        monkeypatch.setattr(voice, "TTS_URL", await server.start())
        speaker = Speaker(httpx.AsyncHTTPTransport())
        try:
            line, deadline = _prepared(speaker, budget=0.3)
            clip = await speaker.stream(line, VOICES[1])
            assert clip.first_at < deadline - voice.FALLBACK_RESERVE_S
            await asyncio.wait_for(server.first_sent.wait(), timeout=0.3)
            await asyncio.wait_for(clip.ended.wait(), timeout=1.0)
            assert clip.chunks == [FIRST]
            assert not clip.whole
            assert server.models == [voice.MODEL]
        finally:
            release_body.set()
            await server.close()

    asyncio.run(run())
