"""The app factory: every route of the spine. The match catalogue, the Moment loader and the
commentator come from data/ and agent/ (#13) through `Deps`, so tests inject their own."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from core import insight
from core.predict import load_pack, shot_points
from core.replay import OFF_AIR, Replay, run_replay
from core.stats import stats
from core.store import open_store
from core.voice import Speaker, voice_router

log = logging.getLogger("night_shift.app")
REJOIN_S = 10.0  # a replay with no open stream this long is stopped: its lines cost model calls
FORGET_S = 60.0  # a finished replay is forgotten this long after REJOIN_S, once nobody streams it

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"


@dataclass
class Deps:
    list_matches: Callable[[], list[dict]]
    load_moments: Callable[[str], list[dict]]
    commentate: Callable[[dict, list[dict]], dict]
    video_map: Callable[[str], dict | None] = lambda match_id: None
    correct: Callable[[dict, str], dict] | None = None
    ask: Callable[[str, list[dict], list[dict]], dict] | None = None


def default_deps() -> Deps:
    """Wire #13's loaders and commentator; None until they land, and the replay routes say 503."""
    try:
        from agent.commentator import answer, commentate, correct
        from data.matches import list_matches, load_moments, video_map
    except ImportError:
        return None
    return Deps(list_matches, load_moments, commentate, video_map, correct, answer)


class ReplayRequest(BaseModel):
    match_id: str
    speed: float = Field(10.0, gt=0)


class FixRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corrected_text: str = Field(min_length=1)
    reason: str = ""


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=200)
    moment_idx: int | None = None  # the last moment on the viewer's screen; None: the latest sent


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


def create_app(store=None, deps: Deps | None = None, tts_transport=None) -> FastAPI:
    app = FastAPI(title="Night Shift")
    store = store or open_store()
    deps = deps or default_deps()
    replays: dict[str, Replay] = {}
    speaker = Speaker(tts_transport)
    tasks: set[asyncio.Task] = set()
    running: dict[str, asyncio.Task] = {}  # replay id: its run_replay task, until it ends
    asking: set[str] = set()  # replay ids with a viewer's question in flight

    def need_deps() -> Deps:
        if deps is None:
            raise HTTPException(503, "commentator not configured")
        return deps

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/matches")
    def matches():
        return need_deps().list_matches()

    @app.post("/replays")
    async def start_replay(req: ReplayRequest):
        d = need_deps()
        try:
            moments = d.load_moments(req.match_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(404, f"no match {req.match_id!r}") from exc
        replay = Replay(req.match_id, req.speed)
        replays[replay.id] = replay
        video = d.video_map(req.match_id)
        task = asyncio.create_task(
            run_replay(
                replay,
                moments,
                d.commentate,
                store,
                video,
                partial(speaker.prepare, replay=replay.id),
            )
        )
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        running[replay.id] = task
        task.add_done_callback(lambda _: running.pop(replay.id, None))
        task.add_done_callback(lambda _: forget_later(replay))
        stop_later(replay)  # in case no stream ever opens
        return {"replay_id": replay.id}

    def stop_later(replay: Replay) -> None:
        if replay.stopping:
            replay.stopping.cancel()
        replay.stopping = asyncio.get_running_loop().call_later(REJOIN_S, abandon, replay)

    def forget_later(replay: Replay) -> None:
        playing = max(0.0, (replay.ends_at or 0.0) - time.monotonic())  # a video still to watch
        asyncio.get_running_loop().call_later(playing + REJOIN_S + FORGET_S, forget, replay)

    def forget(replay: Replay) -> None:
        """Drop a finished replay's events from memory; one still streamed waits another round."""
        if replay.listeners:
            forget_later(replay)
        else:
            replays.pop(replay.id, None)
            speaker.lanes.pop(replay.id, None)

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
        replay = replays.get(replay_id)
        if replay is None:
            raise HTTPException(404, f"no replay {replay_id!r}")

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
                if not replay.listeners:
                    stop_later(replay)

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.get("/lines/{line_id}")
    def get_line(line_id: str):
        line = next((ln for ln in store.all("lines") if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        return line

    @app.post("/lines/{line_id}/fix")
    async def fix_line(line_id: str, req: FixRequest):
        d = need_deps()
        lines = await asyncio.to_thread(store.all, "lines")
        line = next((ln for ln in lines if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        if d.correct is None:
            raise HTTPException(503, "commentator not configured")
        try:
            # an insight or reply goes back with its own Stat request, not its moment's
            over = insight.said_over(line, d.load_moments)
            more = {"moments": over} if over else {}
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
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "mubit_request_id": sent["mubit_request_id"],
                "reply_matched": sent["reply_matched"],
            },
        )
        for replay in list(replays.values()):  # a replay may start during the awaits below
            if any(
                e["data"].get("line_id") == line_id for e in replay.events if e["event"] == "line"
            ):
                await replay.publish("fixed", fix)
                await replay.publish("stats", await asyncio.to_thread(stats, store))
        return fix

    @app.post("/replays/{replay_id}/ask")
    async def ask(replay_id: str, req: AskRequest):
        d = need_deps()
        replay = replays.get(replay_id)
        if replay is None:
            raise HTTPException(404, f"no replay {replay_id!r}")
        if replay_id in asking:
            raise HTTPException(409, "a question is already in flight")
        past, lines = asked_so_far(replay, d.load_moments(replay.match_id), req.moment_idx)
        if not past:
            raise HTTPException(409, "nothing has happened yet")
        asking.add(replay_id)
        try:
            said = await asyncio.to_thread(d.ask, req.question, past, lines) if d.ask else None
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
                "text": OFF_AIR,
                "off_air": True,
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
        replay = replays.get(replay_id)
        if replay is None:
            raise HTTPException(404, f"no replay {replay_id!r}")
        past, _ = asked_so_far(replay, d.load_moments(replay.match_id), moment_idx)
        if not past:
            raise HTTPException(409, "nothing has happened yet")
        pack = load_pack(past[-1]["sport"], replay.match_id)
        try:  # ValueError: a sport with no shot locations (cricket); KeyError: no such player
            if pack is None:
                raise KeyError(replay.match_id)
            return shot_points(pack, past, len(past) - 1, name)
        except (ValueError, KeyError) as exc:
            raise HTTPException(404, f"no shot map for {name!r} in this match") from exc

    @app.get("/stats")
    def get_stats():
        return stats(store)

    @app.get("/stage")
    def stage():
        """The backup demo page: one static file, so the demo runs even without web/."""
        return FileResponse(Path(__file__).with_name("stage.html"), media_type="text/html")

    app.include_router(voice_router(store, speaker))
    # the built page (web/, #18) at /, mounted last so every API route above wins
    if WEB.is_dir():
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app
