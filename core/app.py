"""The app factory: every route of the spine. The match catalogue, the Moment loader and the
commentator come from data/ and agent/ (#13) through `Deps`, so tests inject their own."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from core.replay import Replay, run_replay
from core.stats import stats
from core.store import open_store
from core.voice import Speaker, voice_router

log = logging.getLogger("night_shift.app")
REJOIN_S = 10.0  # a replay with no open stream this long is stopped: its lines cost model calls

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"


@dataclass
class Deps:
    list_matches: Callable[[], list[dict]]
    load_moments: Callable[[str], list[dict]]
    commentate: Callable[[dict, list[dict]], dict]
    video_map: Callable[[str], dict | None] = lambda match_id: None
    correct: Callable[[dict, str], dict] | None = None


def default_deps() -> Deps:
    """Wire #13's loaders and commentator; None until they land, and the replay routes say 503."""
    try:
        from agent.commentator import commentate, correct
        from data.matches import list_matches, load_moments, video_map
    except ImportError:
        return None
    return Deps(list_matches, load_moments, commentate, video_map, correct)


class ReplayRequest(BaseModel):
    match_id: str
    speed: float = Field(10.0, gt=0)


class FixRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    corrected_text: str = Field(min_length=1)
    reason: str = ""


def create_app(store=None, deps: Deps | None = None, tts_transport=None) -> FastAPI:
    app = FastAPI(title="Night Shift")
    store = store or open_store()
    deps = deps or default_deps()
    replays: dict[str, Replay] = {}
    speaker = Speaker(tts_transport)
    tasks: set[asyncio.Task] = set()
    running: dict[str, asyncio.Task] = {}  # replay id: its run_replay task, until it ends

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
            run_replay(replay, moments, d.commentate, store, video, speaker.prepare)
        )
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        running[replay.id] = task
        task.add_done_callback(lambda _: running.pop(replay.id, None))
        stop_later(replay)  # in case no stream ever opens
        return {"replay_id": replay.id}

    def stop_later(replay: Replay) -> None:
        if replay.stopping:
            replay.stopping.cancel()
        replay.stopping = asyncio.get_running_loop().call_later(REJOIN_S, abandon, replay)

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

    @app.post("/lines/{line_id}/fix")
    async def fix_line(line_id: str, req: FixRequest):
        d = need_deps()
        line = next((ln for ln in store.all("lines") if ln.get("line_id") == line_id), None)
        if line is None:
            raise HTTPException(404, f"no line {line_id!r}")
        if d.correct is None:
            raise HTTPException(503, "commentator not configured")
        try:
            sent = await asyncio.to_thread(d.correct, line, req.corrected_text)
        except Exception as exc:  # nothing is stored, so the page can send the fix again
            raise HTTPException(503, f"correction not sent: {exc}") from exc
        fix = store.append(
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
        for replay in replays.values():
            if any(
                e["data"].get("line_id") == line_id for e in replay.events if e["event"] == "line"
            ):
                await replay.publish("fixed", fix)
                await replay.publish("stats", stats(store))
        return fix

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
