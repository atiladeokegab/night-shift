"""The extra flash retry must not start after its hard deadline while waiting for a TTS slot."""

import asyncio
import json

import httpx

from core import voice

KEY = "sk-test-not-a-real-key"
AUDIO = b"test-audio"


def scenario(monkeypatch, release_after):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(voice, "RETRY_S", 0.15)
    calls = []

    async def run():
        last_call = asyncio.Event()
        fail_last = asyncio.Event()
        blocker_entered = asyncio.Event()
        unblock = asyncio.Event()

        async def handle(request):
            calls.append(json.loads(request.content)["model_id"])
            if len(calls) == 3:  # hold the first attempt's final flash failure
                last_call.set()
                await fail_last.wait()
                return httpx.Response(500)
            return httpx.Response(500 if len(calls) < 3 else 200, content=AUDIO)

        speaker = voice.Speaker(httpx.MockTransport(handle))
        speaker.slots = asyncio.Semaphore(1)
        line = {"line_id": "retry-deadline", "sport": "football", "text": "Goal!"}
        task = asyncio.create_task(speaker.audio(line, voice.VOICES[1]))
        await last_call.wait()

        async def hold_slot():
            await speaker.slots.acquire()
            blocker_entered.set()
            await unblock.wait()
            speaker.slots.release()

        key = ("retry-deadline", voice.VOICES[1]["id"])
        original = speaker.clips[key]
        blocker = asyncio.create_task(hold_slot())
        await asyncio.sleep(0)  # queue the blocker ahead of the retry
        fail_last.set()
        await blocker_entered.wait()
        while key not in speaker.clips or speaker.clips[key] is original:
            await asyncio.sleep(0)
        await asyncio.sleep(release_after)
        done_before_release = task.done()
        count_before_release = len(calls)
        unblock.set()
        try:
            result = await asyncio.wait_for(task, timeout=1.0)
        finally:
            if not blocker.done():
                blocker.cancel()
        return done_before_release, count_before_release, result, calls

    return asyncio.run(run())


def test_retry_waiting_past_deadline_finishes_without_starting_tts(monkeypatch):
    done, calls_before_release, result, calls = scenario(monkeypatch, 0.25)
    assert done
    assert calls_before_release == 3
    assert len(calls) == 3
    assert result is None


def test_retry_that_gets_a_slot_in_time_can_succeed(monkeypatch):
    done, calls_before_release, result, calls = scenario(monkeypatch, 0.02)
    assert not done
    assert calls_before_release == 3
    assert result == (AUDIO, "eleven_flash_v2_5")
    assert len(calls) == 4
