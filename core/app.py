"""The app factory: every route of the spine. The match catalogue, the Moment loader and the
commentator come from data/ and agent/ through `Deps`, so tests inject their own."""

import asyncio
import hmac
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core import graph, insight, ledger, predict, review
from core.converse import converse_router
from core.guard import OFF_TODAY, Guard, SayOnly, cached_commentator, client_ip
from core.look import Looks, Unshared
from core.predict import shot_points
from core.replay import OFF_AIR, Replay, run_replay
from core.stats import stats
from core.store import open_store
from core.teams import router as teams_router
from core.voice import Speaker, voice_of, voice_router

log = logging.getLogger("touchline.app")
REJOIN_S = 10.0  # a replay with no open stream this long is stopped: its lines cost model calls
FORGET_S = 60.0  # a finished replay is forgotten once nobody streams or touches it this long

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"


@dataclass
class Deps:
    list_matches: Callable[[], list[dict]]
    load_moments: Callable[[str], list[dict]]
    commentate: Callable[[dict, list[dict]], dict]
    video_map: Callable[..., dict | None] = lambda match_id, start_idx=None: None
    correct: Callable[[dict, str], dict] | None = None
    ask: Callable[[str, list[dict], list[dict]], dict] | None = None
    status: Callable[[list[dict]], dict] | None = None
    fixes: bool = False  # commentate takes `fixes=`: the match's producer fixes go in each request
    linecheck: Callable[[dict, dict, list[dict]], dict] | None = None  # the second opinion (#298)
    teach: Callable[[dict], dict | None] | None = None  # a producer's fix as a Line check example
    # a frame of the viewer's shared screen (base64 JPEG) and the match's names: {"note"}, one note
    # or None, with the call's model and tokens. Set, commentate takes `seen=` too (#291)
    look: Callable[[str, list[str]], dict] | None = None
    # a producer's fix as a Score check example (#321): (line, ids already sent) -> sent or None
    score_teach: Callable[[dict, set[str]], dict | None] | None = None
    record: bool = False  # commentate takes `record=`: a checked line sent again, recorded (#399)


def with_fixes(commentate, store):
    """`commentate` given the match's stored producer fixes on every call, read then."""
    from agent.commentator import match_fixes

    known: dict = {}  # old fix rows' lines, read once

    def call(moment: dict, history: list[dict], **kw) -> dict:
        try:
            fixes = match_fixes(store, moment["match_id"], known)
        except Exception as exc:  # an unreadable store never takes the commentator off air
            log.warning("fixes not read for %s: %s", moment["match_id"], str(exc)[:300])
            fixes = []
        return commentate(moment, history, fixes=fixes, **kw)

    return call


def with_look(commentate, take: Callable[[dict], str | None]):
    """`commentate` given the viewer's latest screen note (#291), when `take` has one for the
    moment."""

    def call(moment: dict, history: list[dict], **kw) -> dict:
        if seen := take(moment):
            kw["seen"] = seen
        return commentate(moment, history, **kw)

    return call


def default_deps() -> Deps:
    """Wire the loaders and the commentator; None if agent/ or data/ fail to import, and the replay
    routes say 503."""
    try:
        from agent.commentator import answer, commentate, correct
        from agent.linecheck import live_check, teach
        from agent.look import see
        from agent.scorecheck import teach as score_teach
        from agent.status import status
        from data.matches import list_matches, load_moments, video_map
    except ImportError:
        return None
    return Deps(
        list_matches,
        load_moments,
        commentate,
        video_map,
        correct,
        answer,
        status,
        True,
        live_check,
        teach,
        see,
        score_teach,
        record=True,
    )


class ReplayRequest(BaseModel):
    match_id: str
    speed: float = Field(10.0, gt=0)
    start_idx: int | None = Field(None, ge=0)  # start at this moment: nothing before it is called
    smoke: bool = False  # the deploy's live smoke (core/smoke.py): not counted as a full replay


class FixRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corrected_text: str = Field(min_length=1, max_length=200)
    reason: str = Field("", max_length=200)  # it goes in later prompts


LOOK_BYTES = 420_000  # a frame's request body: the image's 400 kB and the JSON around it


class LookRequest(BaseModel):
    # one frame of the shared tab, about 512 px wide: base64 JPEG ("/9j/" is its first bytes)
    image: str = Field(min_length=100, max_length=400_000, pattern=r"^/9j/[A-Za-z0-9+/]+={0,2}$")
    t: float = Field(0.0, ge=0)  # the video time it was taken at


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=200)
    moment_idx: int | None = None  # the last moment on the viewer's screen; None: the latest sent


# "Where are we?" asked in words, typed or by voice (#186): the status task answers it, not Ask
STATUS_ASK = re.compile(
    r"(?:so )?(?:where are we|what(?:'s| is) the score|who(?:'s| is) (?:batting|at the crease))"
    r"(?: now| at)?"
)


def wants_status(question: str) -> bool:
    said = re.sub(r"[^\w\s']", " ", question.lower().replace("’", "'"))  # a phone's apostrophe
    return bool(STATUS_ASK.fullmatch(" ".join(said.split())))


def asked_so_far(replay: Replay, moments: list[dict], on_screen: int | None):
    """The moments and lines up to the one on screen, never past the last one the replay has sent:
    the page can hold the window back (a video behind the stream) but never push it forward."""
    sent = [e["data"]["idx"] for e in replay.events if e["event"] == "moment"]
    if not sent:
        return [], []
    upto = max(sent) if on_screen is None else min(on_screen, max(sent))
    past = [m for m in moments if m["idx"] <= upto]
    lines = [
        e["data"] for e in replay.events if e["event"] == "line" and e["data"]["moment_idx"] <= upto
    ]
    return past, lines


def create_app(
    store=None,
    deps: Deps | None = None,
    tts_transport=None,
    guard: Guard | None = None,
    looks: Looks | None = None,
) -> FastAPI:
    app = FastAPI(title="Touchline")
    if not os.environ.get("MUBIT_API_KEY"):
        log.warning("MUBIT_API_KEY unset: Mubit is off, lines use the fallback")
    graph.start()  # once per process; when it fails, Follow a player reads the packs
    store = store or open_store()
    deps = deps or default_deps()
    replays: dict[str, Replay] = {}
    speaker = Speaker(tts_transport, store)
    tasks: set[asyncio.Task] = set()
    running: dict[str, asyncio.Task] = {}  # replay id: its run_replay task, until it ends
    asking: set[str] = set()  # replay ids with a viewer's question in flight
    guard = guard or Guard()
    looks = looks or Looks()  # #291: frames sent and the latest screen note, per replay
    live: set[str] = set()  # replay ids generating new lines, at most guard.max_live (#244)
    said_again: set[str] = set()  # replay ids playing stored lines: no voice is made for them

    def need_deps() -> Deps:
        if deps is None:
            raise HTTPException(503, "commentator not configured")
        return deps

    @app.get("/health")
    def health():
        from agent.commentator import mubit_status

        return {"status": "ok", **mubit_status()}

    @app.get("/matches")
    def matches():
        return need_deps().list_matches()

    @app.get("/matches/{match_id}/start")
    def video_start(match_id: str, at: int):
        """Where the video starts for a replay that jumps to moment `at` (the page's ?at=)."""
        vmap = need_deps().video_map(match_id, at)
        return {"video_start": vmap and vmap["start"]}

    def too_many(wait: int, detail: str) -> HTTPException:
        return HTTPException(429, detail, headers={"Retry-After": str(wait)})

    @app.post("/replays")
    async def start_replay(req: ReplayRequest, request: Request):
        d = need_deps()
        try:
            moments = d.load_moments(req.match_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, f"no match {req.match_id!r}") from exc
        jump = req.start_idx
        if jump is not None and not any(m["idx"] == jump for m in moments):
            raise HTTPException(422, f"no moment {jump} in {req.match_id!r}")
        commentate, speak, correct = d.commentate, speaker.prepare, d.correct
        # the deploy's live smoke stays cheap: no second opinion
        linecheck = checked_under_cap(d.linecheck) if d.linecheck and not req.smoke else None
        if d.fixes:  # a fix applies to the next lines straight away, this replay's too
            commentate = with_fixes(d.commentate, store)
        # shortcut: the cap is checked only as a replay starts, so a running replay can overshoot
        # it by about one replay's cost; check per line in run_replay if that ever matters
        off_air = await asyncio.to_thread(guard.off_air, store)
        cached = off_air or guard.busy(len(live))
        # only a replay that makes new lines counts against the client's hourly starts; over them,
        # the stored lines play instead, which cost nothing
        capped = 0 if cached else guard.replays.hit(client_ip(request))
        cached = cached or bool(capped)
        if cached:  # the lines already stored, said again: no model or voice call, nothing stored
            commentate, speak, correct = cached_commentator(store, req.match_id), None, None
            linecheck = None  # cached playback must not make a paid provider call
            if commentate is None and off_air:
                raise too_many(guard.until_tomorrow(), f"{OFF_TODAY}. Try again tomorrow.")
            if commentate is None and capped:
                raise too_many(
                    capped, "You've started a lot of replays. Try again in a few minutes."
                )
            if commentate is None:
                raise too_many(60, "Lots of people are watching. Try again in a minute.")
        record = None  # a checked line sent again, recorded: never a cached one, nor the smoke's
        if d.record and not cached and not req.smoke:
            fixed = commentate  # before the screen note: a line made from it is never recorded

            def record(moment: dict, history: list[dict]) -> dict | None:
                return fixed(moment, history, record=True)

        # a cached replay cost nothing: never a match for cost per full replay
        replay = Replay(req.match_id, req.speed, req.smoke or cached)
        replays[replay.id] = replay
        # a jump starts the video just before its moment (#163), as GET /matches' peak_video_start
        video = d.video_map(req.match_id) if jump is None else d.video_map(req.match_id, jump)
        said_to = SayOnly(store) if cached else store
        if d.look and not cached and video:  # a frame's note goes in the next line (#291)
            due = {m["idx"]: m["video_t"] for m in video["moments"]}
            commentate = with_look(commentate, lambda m: looks.take(replay.id, due.get(m["idx"])))
            said_to = Unshared(store)  # that line is this viewer's only
        task = asyncio.create_task(
            run_replay(
                replay,
                moments,
                commentate,
                said_to,
                video,
                speak,
                jump or 0,
                correct,
                linecheck,
                record,
            )
        )
        if cached:
            said_again.add(replay.id)
        else:
            live.add(replay.id)
            task.add_done_callback(lambda _: live.discard(replay.id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        running[replay.id] = task
        task.add_done_callback(lambda _: running.pop(replay.id, None))
        task.add_done_callback(lambda _: forget_later(replay))
        stop_later(replay)  # in case no stream ever opens
        return {"replay_id": replay.id}

    def checked_under_cap(linecheck):
        """Line check on a live replay's line, counted toward the daily cap: none over it."""

        def call(line: dict, moment: dict, history: list[dict]) -> dict | None:
            return None if guard.off_air(store) else linecheck(line, moment, history)

        return call

    async def teach(line: dict) -> None:
        """A fix as one Line check example (#298), sent after the fix is answered."""
        try:
            sent = await asyncio.to_thread(need_deps().teach, line)
        except Exception as exc:
            log.warning("line check example for %s not sent: %s", line["line_id"], str(exc)[:300])
            return
        if sent:
            at = datetime.now(UTC).isoformat(timespec="seconds")
            row = {"line_id": line["line_id"], **sent, "created_at": at}
            await asyncio.to_thread(store.append, "linecheck_fixes", row)

    async def score_teach(line: dict, corrected: str) -> None:
        """A fix as Score check examples (#321): the line as said and the producer's text."""
        from eval.seed_scorecheck import send_fix

        try:
            await asyncio.to_thread(send_fix, store, line, corrected, need_deps().score_teach)
        except Exception as exc:
            log.warning("score check example for %s not sent: %s", line["line_id"], str(exc)[:300])

    def stop_later(replay: Replay) -> None:
        if replay.stopping:
            replay.stopping.cancel()
        replay.stopping = asyncio.get_running_loop().call_later(REJOIN_S, abandon, replay)

    def forget_later(replay: Replay) -> None:
        playing = max(0.0, (replay.ends_at or 0.0) - time.monotonic())  # a video still to watch
        asyncio.get_running_loop().call_later(playing + REJOIN_S + FORGET_S, forget, replay)

    def forget(replay: Replay) -> None:
        """Drop a finished replay's events from memory once nobody streams it and no viewer has
        touched it for FORGET_S: a paused page's heartbeat (POST .../seen) keeps it for Ask."""
        idle = time.monotonic() - replay.seen
        if replay.listeners or idle < FORGET_S:
            wait = FORGET_S if replay.listeners else FORGET_S - idle
            asyncio.get_running_loop().call_later(wait, forget, replay)
        else:
            replays.pop(replay.id, None)
            said_again.discard(replay.id)
            looks.forget(replay.id)

    def viewed(replay_id: str) -> Replay:
        """The replay a viewer's request names, marked as still watched."""
        replay = replays.get(replay_id)
        if replay is None:
            raise HTTPException(404, f"no replay {replay_id!r}")
        replay.seen = time.monotonic()
        return replay

    def abandon(replay: Replay) -> None:
        """Stop a replay nobody follows, and its voice jobs, so they free the 3 shared slots."""
        task = running.get(replay.id)
        if replay.listeners or task is None:
            return
        log.warning("replay %s stopped: no stream for %.0f s", replay.match_id, REJOIN_S)
        task.cancel()
        speaker.drop({e["data"]["line_id"] for e in replay.events if e["event"] == "line"})

    @app.get("/replays/{replay_id}/stream")
    async def stream(replay_id: str):
        replay = viewed(replay_id)

        async def sse():
            replay.listeners += 1
            if replay.stopping:
                replay.stopping.cancel()
            try:
                async for e in replay.follow():
                    yield f"event: {e['event']}\ndata: {json.dumps(e['data'])}\n\n"
                yield "event: end\ndata: {}\n\n"
            finally:  # the client went away: a reconnect within REJOIN_S keeps the replay going
                replay.listeners -= 1
                replay.seen = time.monotonic()
                if not replay.listeners:
                    stop_later(replay)

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.post("/replays/{replay_id}/seen", status_code=204)
    def seen(replay_id: str) -> None:
        """The page's heartbeat while it shows the replay, paused or not, once its stream ends."""
        viewed(replay_id)

    @app.get("/lines/{line_id}")
    def get_line(line_id: str):
        line = next((ln for ln in store.all("lines") if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        # its latest fix, Mubit request id included: one correction traced end to end (#239)
        fix = next((f for f in reversed(store.all("fixes")) if f.get("line_id") == line_id), None)
        # the fix sent to Line check as a training example (#305), once it is sent
        sent = [x for x in store.all("linecheck_fixes") if x.get("line_id") == line_id]
        return {
            **line,
            **({"fix": fix} if fix else {}),
            **({"linecheck_example": sent[-1]} if sent else {}),
        }

    @app.post("/lines/{line_id}/fix")
    async def fix_line(line_id: str, req: FixRequest, x_producer_token: str = Header(default="")):
        # a fix trains Mubit and is spoken on later replays (#232): a producer's only, once the
        # deploy sets PRODUCER_TOKEN; unset (local, tests) it is open
        token = os.environ.get("PRODUCER_TOKEN", "")
        if token and not hmac.compare_digest(x_producer_token.encode(), token.encode()):
            raise HTTPException(401, "producer token needed")
        d = need_deps()
        from agent.commentator import fix_context
        from agent.linecheck import TEACHES

        lines = await asyncio.to_thread(store.all, "lines")
        line = next((ln for ln in lines if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        if d.correct is None:
            raise HTTPException(503, "commentator not configured")
        # a fix is spoken on the next replay (#232) and trains Mubit: never one the data contradicts
        if wrong := await asyncio.to_thread(review.wrong, line, req.corrected_text, d):
            raise HTTPException(422, {"wrong": wrong})
        try:
            # an insight or reply goes back with its own Stat request, not its moment's
            over = insight.said_over(line, d.load_moments)
            more = {"moments": over} if over else {}
            if req.reason:  # the correction turn says what was wrong (#245)
                more["reason"] = req.reason
            sent = await asyncio.to_thread(d.correct, line, req.corrected_text, **more)
        except Exception as exc:  # nothing is stored, so the page can send the fix again
            raise HTTPException(503, f"correction not sent: {exc}") from exc
        fix = await asyncio.to_thread(
            store.append,
            "fixes",
            {
                "line_id": line_id,
                "corrected_text": req.corrected_text,
                "reason": req.reason,
                **fix_context(line),  # what later lines' requests carry, without reading "lines"
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "mubit_request_id": sent.get("mubit_request_id"),  # the correction call's (#239)
                "correction": sent.get("correction"),  # the turn Mubit was given (#245)
                "reply_passed": sent.get("reply_passed"),  # its reply passed the number check
                "recorded": sent.get("recorded", False),  # sent to Mubit for training (#161)
            },
        )
        for replay in list(replays.values()):  # a replay may start during the awaits below
            if any(
                e["data"].get("line_id") == line_id for e in replay.events if e["event"] == "line"
            ):
                await replay.publish("fixed", fix)
                await replay.publish("stats", await asyncio.to_thread(stats, store, True))
        if d.teach and req.reason in TEACHES:  # it passed the number check above
            task = asyncio.create_task(teach(line))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if d.score_teach:  # any reason: its label is the data's, and the fix passed the check
            task = asyncio.create_task(score_teach(line, req.corrected_text))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return fix

    @app.post("/replays/{replay_id}/look")
    async def look(replay_id: str, request: Request):
        """One frame of the viewer's shared tab (#291): its note goes in the replay's next line. The
        frame is never stored or logged."""
        size = request.headers.get("content-length", "")
        if size and (not size.isdigit() or int(size) > LOOK_BYTES):
            raise HTTPException(413, "That frame is too big.")
        body = bytearray()
        # a hard limit too: Content-Length can lie or be absent
        async for chunk in request.stream():
            body += chunk
            if len(body) > LOOK_BYTES:
                raise HTTPException(413, "That frame is too big.")
        try:
            req = LookRequest.model_validate_json(bytes(body))
        except ValidationError as exc:  # never the input: it is the frame
            raise RequestValidationError(
                exc.errors(include_url=False, include_input=False)
            ) from None
        d = need_deps()
        replay = viewed(replay_id)
        if d.look is None or replay_id not in live:  # stored lines said again, or the replay ended
            raise HTTPException(410, "the commentators are not watching this replay")
        if looks.over(replay_id):
            raise HTTPException(410, "That's every frame for this replay.")
        if wait := looks.hit(replay_id):
            raise too_many(wait, "One frame every few seconds.")
        if await asyncio.to_thread(guard.off_air, store):
            raise too_many(guard.until_tomorrow(), f"{OFF_TODAY}. Try again tomorrow.")
        moments = d.load_moments(replay.match_id)
        names = [m.get("team") for m in moments] + [
            n for m in moments for n in m["players"].values()
        ]
        try:
            seen = await asyncio.to_thread(d.look, req.image, names)
        except Exception as exc:  # the type only: nothing of the frame reaches the log
            log.warning("look %s: no note: %s", replay.match_id, type(exc).__name__)
            seen = {"note": None}
        note = seen["note"]
        if "model" in seen:  # a call was made: its cost counts toward the daily cap, not the frame
            cost = {k: seen[k] for k in ("model", "tokens_in", "tokens_out")}
            created_at = datetime.now(UTC).isoformat(timespec="seconds")
            record = {"match_id": replay.match_id, "replay_id": replay_id, **cost}
            await asyncio.to_thread(store.append, "looks", {**record, "created_at": created_at})
        if note:
            looks.keep(replay_id, note, req.t)
        return {"note": note}

    @app.post("/replays/{replay_id}/ask")
    async def ask(replay_id: str, req: AskRequest, request: Request):
        d = need_deps()
        replay = viewed(replay_id)
        # read before the in-flight check: no await between that check and asking.add
        off_today = await asyncio.to_thread(guard.off_air, store)
        if replay_id in asking:
            raise HTTPException(409, "a question is already in flight")
        past, lines = asked_so_far(replay, d.load_moments(replay.match_id), req.moment_idx)
        if not past:
            raise HTTPException(409, "nothing has happened yet")
        if wait := guard.asks.hit(client_ip(request)):
            raise too_many(wait, "That's a lot of questions. Try again in a few minutes.")
        asking.add(replay_id)
        try:
            if off_today:
                said = None
            elif d.status and wants_status(req.question):
                said = await asyncio.to_thread(d.status, past)
            else:
                ask = (d.ask, req.question, past, lines)
                said = await asyncio.to_thread(insight.checked_answer, *ask) if d.ask else None
        except Exception as exc:  # the calm off-air state, never the provider's error
            name = type(exc).__name__
            log.warning("ask %s off air: %s: %s", replay.match_id, name, str(exc)[:300])
            said = None
        finally:
            asking.discard(replay_id)
        if said is None:  # nothing stored: there is nothing to speak
            reply = {
                "line_id": uuid.uuid4().hex,
                "moment_idx": past[-1]["idx"],
                "question": req.question,
                "text": OFF_TODAY if off_today else OFF_AIR,
                "off_air": True,
                **({"notice": OFF_TODAY} if off_today else {}),
            }
        else:
            reply = await asyncio.to_thread(
                store.append, "answers", {**said, "replay_id": replay_id}
            )
        await replay.publish("answer", reply)
        return reply

    @app.get("/replays/{replay_id}/players/{name}/shots")
    def shots(replay_id: str, name: str, moment_idx: int | None = None):
        """A player's shot map: pre-match shots plus tonight's up to the moment on screen, never
        past the last moment sent, so a later shot never shows. No LLM: it works off air."""
        d = need_deps()
        replay = viewed(replay_id)
        past, _ = asked_so_far(replay, d.load_moments(replay.match_id), moment_idx)
        if not past:
            raise HTTPException(409, "nothing has happened yet")
        pack = predict.pack(past[-1]["sport"], replay.match_id)
        try:  # ValueError: a sport with no shot locations (cricket); KeyError: no such player
            if pack is None:
                raise KeyError(replay.match_id)
            return shot_points(pack, past, len(past) - 1, name)
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, f"no shot map for {name!r} in this match") from exc

    def pack_so_far(replay_id: str, moment_idx: int | None) -> tuple[dict, list[dict]]:
        """The replay's pack, from the graph or else data/packs, and its moments up to the one on
        screen, cut like the shot map's."""
        d = need_deps()
        replay = viewed(replay_id)
        moments = d.load_moments(replay.match_id)
        sport = moments[0]["sport"] if moments else None
        pack = sport and predict.pack(sport, replay.match_id)
        if not pack:
            raise HTTPException(404, "no pre-match pack for this match")
        return pack, asked_so_far(replay, moments, moment_idx)[0]

    @app.get("/replays/{replay_id}/players")
    def players(replay_id: str, moment_idx: int | None = None):
        """Everyone in the match (#140): the pack's roster plus anyone the moments so far name,
        those first. Works before the first moment, from the roster alone."""
        pack, past = pack_so_far(replay_id, moment_idx)
        return predict.players(pack, past)

    @app.get("/replays/{replay_id}/players/{name}/profile")
    def profile(replay_id: str, name: str, moment_idx: int | None = None):
        """A player's record before the match and tonight up to the moment on screen (#140)."""
        pack, past = pack_so_far(replay_id, moment_idx)
        if not past:
            raise HTTPException(409, "nothing has happened yet")
        try:
            name = predict.find(pack, name)
        except KeyError:  # named in a moment but not in the pack: tonight only
            if name not in {p["name"] for p in predict.players(pack, past)}:
                raise HTTPException(404, "no such player in this match") from None
        out = predict.profile(pack, past, len(past) - 1, name)
        if also := graph.library(pack["sport"], pack["match_id"], name):
            out["library"] = also  # the player's other matches: never this one
        return out

    @app.get("/review")
    def get_review():
        """Stored lead lines the number check flags, for the producer to fix by hand (#171)."""
        return review.queue(store, need_deps())

    @app.get("/ledger")
    def get_ledger():
        """The newest corrections sent to Mubit, with their session and request: cached 30 s."""
        return ledger.cached(store, need_deps())

    @app.get("/stats")
    def get_stats():
        from agent.commentator import mubit_status

        return {
            **stats(store),
            "budget": guard.stats(store),
            "voice": speaker.health(),
            **mubit_status(),
        }

    @app.get("/stage")
    def stage():
        """The backup demo page: one static file, so the demo runs even without web/."""
        return FileResponse(Path(__file__).with_name("stage.html"), media_type="text/html")

    async def voice_on(request: Request) -> None:
        """No new voice over the daily cap, nor for a line a cached replay says: 503, and the page
        uses browser speech."""
        if not request.url.path.endswith("/audio"):
            return
        line_id = request.path_params.get("line_id")
        line = next(
            (
                e["data"]
                for rid in list(said_again)
                for e in (replays[rid].events if rid in replays else [])
                if e["event"] == "line" and e["data"].get("line_id") == line_id
            ),
            None,
        )
        if line is not None:  # its saved audio is played again; none saved: browser speech
            pick = request.query_params.get("voice")
            voice = voice_of(line)["id"] if not pick or line.get("speaker") == "analyst" else pick
            job = speaker.jobs.get((line_id, voice))
            if job and job.done() and not job.cancelled() and not job.exception() and job.result():
                return
            raise HTTPException(503, "voice off for a replay of stored lines")
        if await asyncio.to_thread(guard.off_air, store):
            raise HTTPException(503, "voice off air for today")

    app.include_router(teams_router)
    app.include_router(voice_router(store, speaker), dependencies=[Depends(voice_on)])
    app.include_router(
        converse_router(
            need_deps=need_deps, viewed=viewed, asked_so_far=asked_so_far, guard=guard, store=store
        )
    )
    # the built page (web/, #18) at /, mounted last so every API route above wins; gzipped (#438),
    # the SSE stream and the API not
    if WEB.is_dir():
        app.mount("/", GZipMiddleware(StaticFiles(directory=WEB, html=True)), name="web")
    return app
