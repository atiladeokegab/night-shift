"""The commentator's voice: each stored line read aloud by ElevenLabs, made when the line is created
so it is ready before the video reaches its moment. eleven_v3 with an audio tag for the moment's
kind; one retry, then eleven_flash_v2_5; with no key or every attempt failed the route answers 503
and the page uses browser speech instead. The key stays on the server."""

import asyncio
import logging
import os
import sys
import time
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

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
PREPARED_V3_S = 7.0  # v3's least time for a line made before its moment: late v3 beats flat flash
CONCURRENCY = 3  # a whole match's lines arrive in seconds; ElevenLabs caps concurrent requests
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
    "Shot": "[excited]",
    "Four": "[excited]",
    "Foul Committed": "[excited]",
    "Bad Behaviour": "[excited]",
    "Chase": "[hushed]",
    "End of game": "[shouting]",
    "Steal": "[excited]",
    "Free throw": "[excited]",
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
ANALYST_TAG = "[thoughtful]"  # the analyst's stat lines between moments (#130) are calmer
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


def tag_for(moment: dict) -> str | None:
    if moment.get("outcome") == "Goal" or _big_basket(moment):
        return "[shouting]"
    return TAGS.get(moment.get("type"))


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
        self.tags: dict[str, str | None] = {}
        self.slots = asyncio.Semaphore(CONCURRENCY)
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
        if os.environ.get("ELEVENLABS_API_KEY"):
            self._job(line, voice_of(line), deadline)

    async def audio(self, line: dict, voice: dict, retry=True) -> tuple[bytes, str] | None:
        key = (line["line_id"], voice["id"])
        early = retry and key in self.jobs  # made as the line arrived (prepare)
        job = self._job(line, voice, None)
        try:
            made = await asyncio.shield(job)
        except asyncio.CancelledError:
            if not job.cancelled():  # this request was cancelled, not the job (drop)
                raise
            made = None
        if made is None:  # the next request tries again
            if self.jobs.get(key) is job:  # another waiter may have started the retry already
                del self.jobs[key]
            if early:  # its budget began when the line arrived, not when the page asked (/stage)
                return await self.audio(line, voice, retry=False)
        return made

    def drop(self, line_ids: set[str]) -> None:
        """Cancel these lines' unfinished jobs: an abandoned replay's audio nobody will hear."""
        for key, job in list(self.jobs.items()):
            if key[0] in line_ids and not job.done():
                job.cancel()
                del self.jobs[key]

    def _job(self, line: dict, voice: dict, deadline: float | None) -> asyncio.Task:
        key = (line["line_id"], voice["id"])
        job = self.jobs.pop(key, None)
        if job is None:
            job = asyncio.create_task(self._make(line, voice, deadline))
            job.add_done_callback(lambda _: self._trim())  # pending jobs may have filled the cap
        self.jobs[key] = job  # most recently asked last
        self._trim(keep=key)
        while len(self.tags) > KEEP_JOBS * 4:  # a dropped tag only flattens a re-made line
            del self.tags[next(iter(self.tags))]
        return job

    def _trim(self, keep: tuple[str, str] | None = None) -> None:
        """Forget the least recently asked finished audio past KEEP_JOBS; never unfinished jobs."""
        over = max(0, len(self.jobs) - KEEP_JOBS)
        for old in [k for k, job in self.jobs.items() if job.done() and k != keep][:over]:
            del self.jobs[old]

    async def _make(self, line: dict, voice: dict, deadline: float | None):
        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            return None
        end = deadline if deadline is not None else time.monotonic() + LIVE_BUDGET_S
        model = model_for(line.get("sport"))
        # a viewer's answer (it carries its question) is spoken live, like a call
        if "question" in line:
            said = ANSWER_TAG
        elif line.get("speaker") == "analyst":
            said = ANALYST_TAG
        else:
            said = self.tags.get(line["line_id"])
        tag = said if "v3" in model else None
        text = f"{tag} {line['text']}" if tag else line["text"]
        # made ahead (a video time still to come): one long v3 call, not two squeezed ones
        ahead = deadline is not None and deadline > time.monotonic()
        async with httpx.AsyncClient(transport=self.transport) as client:
            if model != FALLBACK_MODEL:
                for _ in range(1 if ahead else 2):  # a cold first request can time out; retry warm
                    until = min(end - FALLBACK_RESERVE_S, time.monotonic() + V3_TIMEOUT_S)
                    least = PREPARED_V3_S if ahead else 0.0
                    audio = await self._tts(client, key, voice, model, text, until, least)
                    if audio:
                        await self._spent(line, model, text)
                        return audio, model
            until = min(end, time.monotonic() + FALLBACK_TIMEOUT_S)
            audio = await self._tts(
                client, key, voice, FALLBACK_MODEL, line["text"], until, FALLBACK_MIN_S
            )
            if not audio:
                return None
            await self._spent(line, FALLBACK_MODEL, line["text"])
            return audio, FALLBACK_MODEL

    async def _spent(self, line: dict, model: str, text: str) -> None:
        # shortcut: counts calls that returned audio; a timed-out call ElevenLabs still bills is
        # missed, so voice cost is a floor. Its usage API per request if that gap matters.
        if self.store is not None:
            said = {"line_id": line["line_id"], "replay_id": line.get("replay_id")}
            # moment published to this audio ready (#233): the number check, retries and fallback
            # all fall inside it; a line the page asked for again carries no moment_at
            if line.get("moment_at") is not None:
                said["audio_first_ms"] = round((time.monotonic() - line["moment_at"]) * 1000)
            await asyncio.to_thread(
                self.store.append, "voice", {**said, "model": model, "chars": len(text)}
            )

    async def _tts(self, client, key, voice, model, text, until, least=0.0) -> bytes | None:
        # shortcut: every call tries the main key first, so a spent key costs one quick 401 a line
        # and credits added come back at once; remember the working key if that 401 ever matters
        for backup, k in enumerate([key, *backup_keys()]):
            resp = await self._post(client, k, voice["eleven_id"], model, text, until, least)
            if (
                backup
                and resp is not None
                and resp.status_code == 402
                and voice["eleven_id"] != GEORGE
            ):
                # a free-plan backup key can't speak library voices: once more as George
                resp = await self._post(client, k, GEORGE, model, text, until, least)
            if resp is None:
                return None
            if failure(resp) != "quota_exceeded":
                break
        if resp.status_code != 200 or not resp.content:
            log.warning("voice %s answered %d", model, resp.status_code)
            self._failed(failure(resp))
            return None
        self.failing = None
        return resp.content

    async def _post(
        self, client, key, eleven_id, model, text, until, least
    ) -> httpx.Response | None:
        async with self.slots:
            left = max(until - time.monotonic(), least)
            if left <= 0:  # it would land after the moment
                log.warning("voice %s skipped: out of time", model)
                return None
            try:
                # httpx's timeout is per read: only this bounds the request plus every chunk
                async with asyncio.timeout(left):
                    resp = await client.post(
                        TTS_URL.format(voice=eleven_id),
                        params={"output_format": "mp3_44100_128"},
                        headers={"xi-api-key": key, "accept": "audio/mpeg"},
                        json={"text": text, "model_id": model},
                        timeout=left,
                    )
            except (httpx.HTTPError, TimeoutError) as exc:
                log.warning("voice %s failed: %s", model, type(exc).__name__)
                timeout = isinstance(exc, (TimeoutError, httpx.TimeoutException))
                self._failed("timeout" if timeout else "network")
                return None
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


def voice_router(store, speaker: Speaker) -> APIRouter:
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
    async def line_audio(line_id: str, voice: str | None = None):
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
    took = warm(key, env=env_with_dotenv())
    for vid, ms in took.items():
        print(f"warm {vid}: {'FAILED' if ms is None else f'{ms} ms'}")
    sys.exit(1 if None in took.values() else 0)
