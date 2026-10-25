"""The commentator's voice: each stored line read aloud by ElevenLabs, made when the line is created
so it is ready before the video reaches its moment. eleven_v3 with an audio tag for the moment's
kind; one retry, then eleven_flash_v2_5, then (a timeout or upstream error) one short flash call
more; with no key or every attempt failed the route answers 503 and the page uses browser speech
instead. ElevenLabs streams the audio and the route passes it on from the first chunk, so the page
starts playing before the whole file is made. The key stays on the server."""

import asyncio
import logging
import os
import re
import sys
import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, StreamingResponse

log = logging.getLogger("touchline.voice")

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
METER_URL = "https://api.elevenlabs.io/v1/user/subscription"
METER_TTL_S = 300.0  # /stats reads the characters left at most once per 5 minutes
METER_TIMEOUT_S = 3.0
GEORGE = "JBFqnCBsd6RMkjVDRZzb"  # the one voice a free-plan backup key may speak
MODEL = "eleven_v3"  # VOICE_MODEL_<SPORT> overrides it per sport
FALLBACK_MODEL = "eleven_flash_v2_5"  # no audio tags: it would read "[shouting]" aloud
V3_TIMEOUT_S = 20.0  # v3 takes 2-3 s warm, 11-15 s on a cold first request
FALLBACK_TIMEOUT_S = 10.0
FALLBACK_RESERVE_S = 1.5  # v3 stops this long before the moment, so flash still lands in time
FALLBACK_MIN_S = 1.5  # flash always gets this long once it has a slot: a little late beats silence
LIVE_BUDGET_S = 4.0  # a line with no video time is spoken as it arrives
RETRY_S = 3.0  # a page's line that failed before any audio: one flash call this long, then 503
TRANSIENT = ("timeout", "network", "empty")  # failures a second try may get past, as do 5xx
PREPARED_V3_S = 7.0  # v3's least time for a line made before its moment: late v3 beats flat flash
CONCURRENCY = 3  # a whole match's lines arrive in seconds; ElevenLabs caps concurrent requests
BREAKER_S = 20.0  # after a 429, no TTS call this long: queued lines go straight to subtitles
KEEP_JOBS = 500  # finished audio kept, least recently asked first out: ~25 MB at ~50 KB a line

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
        "label": "Sam, Engaging Game Narrator",
        "default_for": "basketball",
        "eleven_id": "gnPxliFHTp6OK6tcoA6i",
    },
    {
        "id": "announcer",
        "lang": "en-GB",
        "label": "British Football Announcer",
        "default_for": "f1",
        "eleven_id": "gU0LNdkMOQCOrPrwtbee",
    },
]

# A moment's kind to the eleven_v3 audio tag it is read with; anything else is read plainly.
TAGS = {
    "Wicket": "[shouting]",
    "Six": "[shouting]",
    "Last ball": "[shouting]",
    "Chase": "[hushed]",
    "End of game": "[shouting]",
    "Lead change": "[shouting]",  # f1: an overtake for the lead
    "Red flag": "[shouting]",  # a crash stops the race
    "Finish": "[shouting]",
    "Full time": "[shouting]",
    "Lights out": "[excited]",
    "Overtake": "[excited]",
    "Pit stop": "[excited]",
    "Safety car": "[excited]",
    "Conditions": "[hushed]",  # build-up: rain and low grip
    "Last lap": "[hushed]",
}

ANSWER_TAG = "[excited]"
ANALYST_TAG = None  # the analyst's stat lines between moments (#130) read plain, like the lead's
# What the two commentators call each other (#221): only the analyst's and reply requests carry
# them, never the lead's recorded moment prompt
NAMES = {"lead": "Jim", "analyst": "Julian"}

# The second commentator per sport (#131): a library voice with another accent than the lead.
ANALYST_FOR = {"cricket": "george", "football": "sam", "basketball": "george", "f1": "sam"}


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


def _call_tag(moment: dict) -> str | None:
    if moment.get("outcome") == "Goal" or _big_basket(moment):
        return "[shouting]"
    return TAGS.get(moment.get("type"))


def _goal_stakes(m: dict) -> str | None:
    """A football goal from the state of the game: level, a go-ahead or a one-goal game is high, a
    goal in a late two-goal game too; a goal that makes it three or more is medium (#378)."""
    score = m.get("score") or {}
    if m.get("sport") != "football" or m.get("outcome") != "Goal" or "home" not in score:
        return None
    margin = abs(score["home"] - score["away"])
    try:
        late = int(str(m.get("clock")).split(":")[0]) >= 80
    except ValueError:
        late = False
    return "high" if margin <= 1 or (late and margin == 2) else "medium"


def intensity(moment: dict) -> str:
    """How big a moment is: the tag its call gets, and for a football goal the game's state; a stat
    line is always calm, whatever it follows (the lead's call, over #378's shared lift)."""
    if moment.get("type") == "Stat":
        return "calm"
    return _goal_stakes(moment) or {"[shouting]": "high", "[excited]": "medium"}.get(
        _call_tag(moment), "calm"
    )


# eleven_v3 takes stability at 0 (creative), 0.5 (natural) or 1 (robust) only
STABILITY = {"high": 0.0, "medium": 0.5, "calm": 0.5}


def tag_for(moment: dict) -> str | None:
    if moment.get("type") == "Stat":  # a stat line or comeback reads plain, whatever it follows
        return None
    tag = _call_tag(moment)
    return None if tag == "[shouting]" and intensity(moment) == "medium" else tag  # not a big one


def all_voices(env=os.environ) -> list[dict]:
    """VOICES, plus `<sport>-pick` for each VOICE_<SPORT> set to a raw ElevenLabs voice id or to
    another sport's default: /voices names one sport per voice, so a shared one needs its own."""
    picks = []
    for v in VOICES:
        sport = v["default_for"]
        chosen = env.get(f"VOICE_{sport.upper()}") if sport else None
        ours = next((x for x in VOICES if x["id"] == chosen), None)
        if chosen and (ours is None or ours["default_for"] not in (None, sport)):
            eleven_id = ours["eleven_id"] if ours else chosen
            label = env.get(f"VOICE_LABEL_{sport.upper()}") or (
                ours["label"] if ours else f"{sport.title()} pick"
            )
            picks.append({**v, "id": f"{sport}-pick", "label": label, "eleven_id": eleven_id})
    return VOICES + picks


def default_voice(sport: str | None, env=os.environ) -> dict:
    chosen = env.get(f"VOICE_{str(sport).upper()}")
    voices = all_voices(env)
    return (
        next((v for v in voices if v["id"] == f"{sport}-pick"), None)
        or next((v for v in voices if v["id"] == chosen), None)
        or next((v for v in VOICES if v["default_for"] == sport), VOICES[0])
    )


def analyst_voice(sport: str | None, env=os.environ) -> dict:
    """The sport's analyst, never the lead's voice: a deployed lead pick may take the analyst's, and
    then another voice stands in, another accent first."""
    lead = default_voice(sport, env)
    others = [v for v in all_voices(env) if v["eleven_id"] != lead["eleven_id"]]
    pick = next((v for v in others if v["id"] == ANALYST_FOR.get(str(sport))), None)
    return pick or min(others, key=lambda v: v["lang"] == lead["lang"])


def model_for(sport: str | None, env=os.environ) -> str:
    return env.get(f"VOICE_MODEL_{str(sport).upper()}") or MODEL  # empty in .env means unset


def failure(resp: httpx.Response) -> str:
    """Why ElevenLabs refused: its own `detail.status` on a 401 or 429 (e.g. "quota_exceeded"), else
    the HTTP status."""
    if resp.status_code in (401, 429):
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = None
        if isinstance(detail, dict) and detail.get("status"):
            return str(detail["status"])
    return str(resp.status_code) if resp.status_code != 200 else "empty"


def backup_keys(env=os.environ) -> list[str]:
    """ELEVENLABS_API_KEY_FALLBACKS: comma-separated keys tried in order once the main key's quota
    is gone."""
    return [k.strip() for k in env.get("ELEVENLABS_API_KEY_FALLBACKS", "").split(",") if k.strip()]


class Clip:
    """One line's audio as ElevenLabs streams it: the page starts playing at the first chunk while
    the rest arrives, instead of waiting for the whole file."""

    def __init__(self):
        self.chunks: list[bytes] = []
        self.model: str | None = None
        self.first_at: float | None = None  # time.monotonic() of the first chunk
        self.whole = False  # every chunk arrived
        self.failed: str | None = None  # why the last call gave no audio, as failure() names it
        self.ready = asyncio.Event()  # the first chunk is here, or the job ended without one
        self.ended = asyncio.Event()
        self._more = asyncio.Event()  # set, then replaced, at each chunk and at the end

    def add(self, chunk: bytes, model: str) -> None:
        if self.first_at is None:
            self.first_at, self.model = time.monotonic(), model
            self.ready.set()
        self.chunks.append(chunk)
        self._wake()

    def end(self, job: asyncio.Task) -> None:
        self.whole = not job.cancelled() and job.exception() is None and job.result() is not None
        self.ended.set()
        self.ready.set()
        self._wake()

    def _wake(self) -> None:
        self._more.set()
        self._more = asyncio.Event()

    async def follow(self):
        """Every chunk so far, then each as it arrives, until the job ends."""
        sent = 0
        while True:
            more = self._more
            while sent < len(self.chunks):
                yield self.chunks[sent]
                sent += 1
            if self.ended.is_set() and sent == len(self.chunks):
                return
            await more.wait()


def voice_of(line: dict) -> dict:
    """Who reads a line when the page picks no voice: the analyst's lines in the analyst voice."""
    if line.get("speaker") == "analyst":
        return analyst_voice(line.get("sport"))
    return default_voice(line.get("sport"))


class Speaker:
    """Each line's audio per voice, made once and kept. The tag goes into the TTS text only, never
    into the stored line or anything sent to Mubit."""

    # shortcut: the last KEEP_JOBS lines' audio is kept in this process's memory; a bucket if
    # older lines must replay with ElevenLabs audio or Cloud Run runs more than one instance.
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, store=None):
        self.transport = transport
        self.store = store  # gets a `voice` record per line spoken: the characters billed (#174)
        self.jobs: dict[tuple[str, str], asyncio.Task] = {}
        self.clips: dict[tuple[str, str], Clip] = {}  # each job's audio as it streams in
        self.tags: dict[str, str | None] = {}
        self.stability: dict[str, float] = {}
        self.stats: dict[str, bool] = {}  # a stat line is spoken calm: its "!" read as "."
        self.slots = asyncio.Semaphore(CONCURRENCY)
        self.closed_until = 0.0  # time.monotonic() the 429 breaker lets calls through again
        # shortcut: per process; one Cloud Run instance today, a shared store if it ever runs more
        self.failing: dict | None = (
            None  # {last_error, since} until ElevenLabs answers again (#306)
        )
        self.meter: tuple[float, int | None] | None = None  # (when read, characters left)

    def health(self) -> dict:
        """Who speaks the lines: ElevenLabs, or the browser since ElevenLabs last failed."""
        if not os.environ.get("ELEVENLABS_API_KEY"):
            return {
                "provider": "browser",
                "last_error": "not_configured",
                "since": None,
                "characters_left": None,
            }
        failing = self.failing or {"last_error": None, "since": None}
        return {
            "provider": "browser" if self.failing else "elevenlabs",
            **failing,
            "characters_left": self.characters_left(),
        }

    def characters_left(self) -> int | None:
        """The main key's character_limit minus character_count, read at most every METER_TTL_S;
        None when it can't be read."""
        if self.meter and time.monotonic() - self.meter[0] < METER_TTL_S:
            return self.meter[1]
        try:
            with httpx.Client(transport=self.transport, timeout=METER_TIMEOUT_S) as client:
                resp = client.get(
                    METER_URL, headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
                )
                sub = resp.raise_for_status().json()
            left = int(sub["character_limit"]) - int(sub["character_count"])
        except Exception as exc:  # the meter never breaks /stats; the type only, never the key
            log.warning("voice meter failed: %s", type(exc).__name__)
            left = None
        self.meter = (time.monotonic(), left)
        return left

    def _failed(self, kind: str) -> None:
        since = (self.failing or {}).get("since") or datetime.now(UTC).isoformat(timespec="seconds")
        if kind == "quota_exceeded" and not self.failing:
            log.error("ElevenLabs quota exceeded: lines fall back to browser speech")
        self.failing = {"last_error": kind, "since": since}

    def prepare(self, line: dict, moment: dict, deadline: float | None = None) -> None:
        """Start the line's audio in its sport's voice; `deadline` is when (time.monotonic) its
        moment plays, None to speak it as it arrives."""
        self.tags[line["line_id"]] = tag_for(moment)
        self.stability[line["line_id"]] = STABILITY[intensity(moment)]
        self.stats[line["line_id"]] = moment.get("type") == "Stat"
        if os.environ.get("ELEVENLABS_API_KEY"):
            self._job(line, voice_of(line), deadline)

    async def audio(self, line: dict, voice: dict) -> tuple[bytes, str] | None:
        """The line's whole audio and the model that spoke it; None if it failed."""
        clip = await self.stream(line, voice)
        if clip is None:
            return None
        await clip.ended.wait()
        return (b"".join(clip.chunks), clip.model) if clip.whole else None

    async def stream(self, line: dict, voice: dict, retry=True) -> Clip | None:
        """The line's audio as soon as its first chunk is here, the rest following; None if it
        failed before any audio."""
        key = (line["line_id"], voice["id"])
        early = retry and key in self.jobs  # made as the line arrived (prepare)
        job = self._job(line, voice, None)
        clip = self.clips[key]
        await clip.ready.wait()
        if clip.chunks:
            return clip
        if not job.cancelled():  # cancelled by drop: no audio
            job.result()  # raises what the job raised
        if early:  # its budget began when the line arrived, not when the page asked (/stage)
            return await self.stream(line, voice, retry=False)
        # failed before any audio, and a try might help (never a spent quota or a bad key): flash
        # once more, briefly, before the browser speaks
        if retry and clip.failed and (clip.failed in TRANSIENT or clip.failed.startswith("5")):
            self._job(line, voice, None, again=True)
            return await self.stream(line, voice, retry=False)
        return None

    def drop(self, line_ids: set[str]) -> None:
        """Cancel these lines' unfinished jobs: an abandoned replay's audio nobody will hear."""
        for key, job in list(self.jobs.items()):
            if key[0] in line_ids and not job.done():
                job.cancel()
                self._forget(key)

    def _job(
        self, line: dict, voice: dict, deadline: float | None, again: bool = False
    ) -> asyncio.Task:
        key = (line["line_id"], voice["id"])
        job = self.jobs.pop(key, None)
        if job is None:
            clip = self.clips[key] = Clip()
            job = asyncio.create_task(self._make(line, voice, deadline, clip, again))
            job.add_done_callback(lambda done: self._ended(key, done, clip))
        self.jobs[key] = job  # most recently asked last
        self._trim(keep=key)
        while len(self.tags) > KEEP_JOBS * 4:  # a dropped tag only flattens a re-made line
            del self.tags[next(iter(self.tags))]
        while len(self.stability) > KEEP_JOBS * 4:
            del self.stability[next(iter(self.stability))]
        while len(self.stats) > KEEP_JOBS * 4:
            del self.stats[next(iter(self.stats))]
        return job

    def _ended(self, key: tuple[str, str], job: asyncio.Task, clip: Clip) -> None:
        clip.end(job)
        # no audio, or cut off mid-stream: the next request makes it again
        if not clip.whole and self.jobs.get(key) is job:  # unless a retry has started already
            self._forget(key)
        self._trim()  # pending jobs may have filled the cap

    def _trim(self, keep: tuple[str, str] | None = None) -> None:
        """Forget the least recently asked finished audio past KEEP_JOBS; never unfinished jobs."""
        over = max(0, len(self.jobs) - KEEP_JOBS)
        for old in [k for k, job in self.jobs.items() if job.done() and k != keep][:over]:
            self._forget(old)

    def _forget(self, key: tuple[str, str]) -> None:
        del self.jobs[key]
        self.clips.pop(key, None)

    async def _make(
        self, line: dict, voice: dict, deadline: float | None, clip: Clip, again: bool = False
    ):
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            return None
        if again:
            end = time.monotonic() + RETRY_S
        else:
            end = deadline if deadline is not None else time.monotonic() + LIVE_BUDGET_S
        model = FALLBACK_MODEL if again else model_for(line.get("sport"))
        # a viewer's answer (it carries its question) is spoken live, like a call
        if "question" in line:
            said = ANSWER_TAG
        elif line.get("speaker") == "analyst":
            said = self.tags.get(line["line_id"], ANALYST_TAG)
        else:
            said = self.tags.get(line["line_id"])
        tag = said if "v3" in model else None
        text = line["text"]
        if self.stats.get(line["line_id"]) and "question" not in line:
            text = re.sub(r"!+", ".", re.sub(r"\?!+", "?", text))  # read calm, not hot
        text = f"{tag} {text}" if tag else text
        # made ahead (a video time still to come): one long v3 call, not two squeezed ones
        ahead = deadline is not None and deadline > time.monotonic()
        async with httpx.AsyncClient(transport=self.transport) as client:
            if model != FALLBACK_MODEL:
                for _ in range(1 if ahead else 2):  # a cold first request can time out; retry warm
                    until = min(end - FALLBACK_RESERVE_S, time.monotonic() + V3_TIMEOUT_S)
                    least = PREPARED_V3_S if ahead else 0.0
                    audio = await self._tts(
                        client,
                        key,
                        voice,
                        model,
                        text,
                        until,
                        least,
                        clip,
                        self.stability.get(line["line_id"]),
                    )
                    if audio:
                        await self._spent(line, model, text, clip, voice, audio)
                        return audio, model
                    if clip.chunks:  # cut off mid-stream: the page has played part of it
                        return None
            until = min(end, time.monotonic() + FALLBACK_TIMEOUT_S)
            audio = await self._tts(
                client,
                key,
                voice,
                FALLBACK_MODEL,
                line["text"],
                until,
                FALLBACK_MIN_S,
                clip,
                hard_deadline=end if again else None,
            )
            if not audio:
                return None
            await self._spent(line, FALLBACK_MODEL, line["text"], clip, voice, audio)
            return audio, FALLBACK_MODEL

    async def _spent(
        self, line: dict, model: str, text: str, clip: Clip, voice: dict, audio: bytes
    ) -> None:
        # shortcut: counts calls that returned audio; a timed-out call ElevenLabs still bills is
        # missed, so voice cost is a floor. Its usage API per request if that gap matters.
        if self.store is not None:
            said = {"line_id": line["line_id"], "replay_id": line.get("replay_id")}
            # moment published to its first audio chunk, when the page can start playing (#233):
            # the number check, retries and fallback all fall inside it; a line the page asked
            # for again carries no moment_at
            if line.get("moment_at") is not None:
                said["audio_first_ms"] = round((clip.first_at - line["moment_at"]) * 1000)
            await asyncio.to_thread(
                self.store.append,
                "voice",
                {
                    **said,
                    "model": model,
                    "chars": len(text),
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
            try:  # kept, so a replay of the line plays this clip and never pays for it again
                await asyncio.to_thread(
                    self.store.save_clip, line["line_id"], voice["id"], audio, "audio/mpeg"
                )
            except Exception as exc:  # the clip is still played; only the saved copy is lost
                log.warning("clip for %s not saved: %s", line["line_id"], str(exc)[:300])

    async def _tts(
        self,
        client,
        key,
        voice,
        model,
        text,
        until,
        least,
        clip,
        stability=None,
        hard_deadline=None,
    ) -> bytes | None:
        # shortcut: every call tries the main key first, so a spent key costs one quick 401 a line
        # and credits added come back at once; remember the working key if that 401 ever matters
        for backup, k in enumerate([key, *backup_keys()]):
            resp = await self._post(
                client,
                k,
                voice["eleven_id"],
                model,
                text,
                until,
                least,
                clip,
                stability,
                hard_deadline,
            )
            if (
                backup
                and resp is not None
                and resp.status_code == 402
                and voice["eleven_id"] != GEORGE
            ):
                # a free-plan backup key can't speak library voices: once more as George
                resp = await self._post(
                    client, k, GEORGE, model, text, until, least, clip, stability, hard_deadline
                )
            if resp is None:
                return None
            if failure(resp) != "quota_exceeded":
                break
        if resp.status_code != 200 or not clip.chunks:
            log.warning("voice %s answered %d", model, resp.status_code)
            if resp.status_code == 429:  # every key tried: more calls now would only pile up
                self.closed_until = time.monotonic() + BREAKER_S
            clip.failed = failure(resp)
            self._failed(clip.failed)
            return None
        self.failing = None
        return b"".join(clip.chunks)

    async def _post(
        self,
        client,
        key,
        eleven_id,
        model,
        text,
        until,
        least,
        clip,
        stability=None,
        hard_deadline=None,
    ) -> httpx.Response | None:
        """One TTS call, streamed into `clip` chunk by chunk; the response, read only when it
        failed (failure() reads its body), or None when it timed out or the network failed."""
        if hard_deadline is not None:
            wait = hard_deadline - time.monotonic()
            if wait <= 0:
                log.warning("voice %s skipped: retry deadline passed", model)
                return None
            try:
                async with asyncio.timeout(wait):
                    await self.slots.acquire()
            except TimeoutError:
                log.warning("voice %s retry expired waiting for a slot", model)
                return None
        else:
            await self.slots.acquire()
        try:
            left = (
                max(until - time.monotonic(), least)
                if hard_deadline is None
                else hard_deadline - time.monotonic()
            )
            if left <= 0:  # it would land after the moment or retry deadline
                log.warning("voice %s skipped: out of time", model)
                return None
            if time.monotonic() < self.closed_until:
                log.warning("voice %s skipped: ElevenLabs rate limit", model)
                return None
            # httpx's timeout is per read: only this bounds the wait for the first chunk
            async with (
                asyncio.timeout(left) as bound,
                client.stream(
                    "POST",
                    TTS_URL.format(voice=eleven_id) + "/stream",
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": key, "accept": "audio/mpeg"},
                    json={
                        "text": text,
                        "model_id": model,
                        **(
                            {"voice_settings": {"stability": stability}}
                            if stability is not None and "v3" in model
                            else {}
                        ),
                    },
                    timeout=V3_TIMEOUT_S,
                ) as resp,
            ):
                if resp.status_code != 200:
                    await resp.aread()
                    return resp
                async for chunk in resp.aiter_bytes():
                    if not clip.chunks:  # playing from here, so the rest may run past `until`
                        bound.reschedule(asyncio.get_running_loop().time() + V3_TIMEOUT_S)
                    clip.add(chunk, model)
        except (httpx.HTTPError, TimeoutError) as exc:
            log.warning("voice %s failed: %s", model, type(exc).__name__)
            timeout = isinstance(exc, (TimeoutError, httpx.TimeoutException))
            clip.failed = "timeout" if timeout else "network"
            self._failed(clip.failed)
            return None
        finally:
            self.slots.release()
        return resp


def warm(
    key: str, transport: httpx.BaseTransport | None = None, env=os.environ
) -> dict[str, int | None]:
    """Speak one short line in every voice, the sport picks included, on both models and its
    sport's VOICE_MODEL_<SPORT>; ms per voice, None if one failed. A shared voice is spoken once."""
    took, warmed, quota = {}, {}, False
    with httpx.Client(transport=transport, timeout=30) as client:
        for v in all_voices(env):
            started = time.perf_counter()
            ok = True
            for model in dict.fromkeys((MODEL, model_for(v["default_for"], env), FALLBACK_MODEL)):
                if (v["eleven_id"], model) not in warmed:
                    try:
                        resp = client.post(
                            TTS_URL.format(voice=v["eleven_id"]),
                            params={"output_format": "mp3_44100_128"},
                            headers={"xi-api-key": key, "accept": "audio/mpeg"},
                            json={"text": "And we're live.", "model_id": model},
                        )
                        warmed[v["eleven_id"], model] = resp.status_code == 200 and bool(
                            resp.content
                        )
                        if not warmed[v["eleven_id"], model] and failure(resp) == "quota_exceeded":
                            quota = True  # every line would be browser speech
                    except httpx.HTTPError:
                        warmed[v["eleven_id"], model] = False
                ok = ok and warmed[v["eleven_id"], model]
            took[v["id"]] = round((time.perf_counter() - started) * 1000) if ok else None
    if quota:
        log.error("ELEVENLABS QUOTA EXCEEDED: every line falls back to browser speech; add credits")
    return took


def env_with_dotenv(path=".env", env=os.environ) -> dict:
    """The environment, plus VOICE_* settings from .env that it leaves unset, as deploy.sh reads
    them: the picks in .env are the ones to warm. Nothing else is read from .env."""
    out = dict(env)
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    for line in lines:
        name, _, value = line.partition("=")
        if name.startswith("VOICE_") and not out.get(name):
            out[name] = value.strip().strip("\"'")
    return out


def safari(user_agent: str | None) -> bool:
    """Safari, desktop or iOS (every iOS browser is Safari underneath): it may not play a chunked
    mp3 with no length, so it gets the whole file."""
    ua = user_agent or ""
    if "iPhone" in ua or "iPad" in ua:
        return True
    return "Safari" in ua and not any(
        b in ua for b in ("Chrome", "Chromium", "CriOS", "FxiOS", "Android")
    )


def voice_router(store, speaker: Speaker, off_air=lambda: False) -> APIRouter:
    router = APIRouter()

    @router.get("/voices")
    def voices():
        sports = sorted({v["default_for"] for v in VOICES if v["default_for"]}, reverse=True)
        default = {default_voice(s)["id"]: s for s in sports}  # one sport per voice
        voices = all_voices()
        first = {}  # a pick reusing a voice names the entry it repeats, so the page lists it once
        for v in voices:
            first.setdefault(v["eleven_id"], v["id"])
        analyst = {s: analyst_voice(s)["id"] for s in sports}  # the page names who reads them
        return [
            {**{k: v[k] for k in ("id", "label", "lang")}, "default_for": default.get(v["id"])}
            | ({"same_as": first[v["eleven_id"]]} if first[v["eleven_id"]] != v["id"] else {})
            | ({"analyst_for": a} if (a := [s for s in sports if analyst[s] == v["id"]]) else {})
            for v in voices
        ]

    @router.get("/lines/{line_id}/audio")
    async def line_audio(
        line_id: str, voice: str | None = None, user_agent: str | None = Header(None)
    ):
        # only stored lines, answers and screen-note lines (#291) are spoken, so the key can't read
        # out arbitrary text
        kinds = ("lines", "answers", "looks")
        said = await asyncio.to_thread(lambda: [x for k in kinds for x in store.all(k)])
        line = next((ln for ln in said if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        if voice:
            chosen = next((v for v in all_voices() if v["id"] == voice), None)
            if chosen is None:
                raise HTTPException(404, f"no voice {voice!r}")
        # the page's pick is the lead's voice; the analyst follows the sport
        if not voice or line.get("speaker") == "analyst":
            chosen = voice_of(line)
        # made once and saved: served again with no ElevenLabs call, on any instance
        if saved := await asyncio.to_thread(store.clip, line_id, chosen["id"]):
            log.info("voice line=%s saved", line_id)
            return Response(saved[0], media_type=saved[1])
        if await asyncio.to_thread(off_air):  # no new voice over the daily cap: browser speech
            raise HTTPException(503, "voice off air for today")
        if not os.environ.get("ELEVENLABS_API_KEY"):
            raise HTTPException(503, "voice not configured")
        started = time.perf_counter()
        clip = await speaker.stream(line, chosen)
        if clip is None:
            raise HTTPException(503, "voice upstream failed")
        ms = (time.perf_counter() - started) * 1000
        log.info("voice line=%s first_byte_ms=%d model=%s", line_id, ms, clip.model)
        if safari(user_agent):
            await clip.ended.wait()
            if not clip.whole:  # cut off mid-stream: no whole file to send
                raise HTTPException(503, "voice upstream failed")
        if clip.whole:  # made already, or for Safari: a plain file, with its length
            return Response(b"".join(clip.chunks), media_type="audio/mpeg")
        return StreamingResponse(clip.follow(), media_type="audio/mpeg")

    return router


if __name__ == "__main__":
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    took = warm(key, env=env_with_dotenv())
    for vid, ms in took.items():
        print(f"warm {vid}: {'FAILED' if ms is None else f'{ms} ms'}")
    sys.exit(1 if None in took.values() else 0)
