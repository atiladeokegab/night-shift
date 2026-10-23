"""The app factory: every route of the spine. The match catalogue, the Moment loader and the
commentator come from data/ and agent/ (#13) through `Deps`, so tests inject their own."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.replay import Replay, run_replay
from core.stats import stats
from core.store import open_store
from core.voice import voice_router


@dataclass
class Deps:
    list_matches: Callable[[], list[dict]]
    load_moments: Callable[[str], list[dict]]
    commentate: Callable[[dict, list[dict]], dict]


def default_deps() -> Deps:
    """Wire #13's loaders and commentator; None until they land, and the replay routes say 503."""
    try:
        from agent.commentator import commentate
        from data.matches import list_matches, load_moments
    except ImportError:
        return None
    return Deps(list_matches, load_moments, commentate)


class ReplayRequest(BaseModel):
    match_id: str
    speed: float = Field(10.0, gt=0)


def create_app(store=None, deps: Deps | None = None, tts_transport=None) -> FastAPI:
    app = FastAPI(title="Night Shift")
    store = store or open_store()
    deps = deps or default_deps()
    replays: dict[str, Replay] = {}
    tasks: set[asyncio.Task] = set()

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
        task = asyncio.create_task(run_replay(replay, moments, d.commentate, store))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"replay_id": replay.id}

    @app.get("/replays/{replay_id}/stream")
    async def stream(replay_id: str):
        replay = replays.get(replay_id)
        if replay is None:
            raise HTTPException(404, f"no replay {replay_id!r}")

        async def sse():
            async for e in replay.follow():
                yield f"event: {e['event']}\ndata: {json.dumps(e['data'])}\n\n"
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream")

    @app.get("/stats")
    def get_stats():
        return stats(store)

    @app.get("/stage")
    def stage():
        """The backup demo page: one static file, so the demo runs even without web/."""
        return FileResponse(Path(__file__).with_name("stage.html"), media_type="text/html")

    app.include_router(voice_router(store, tts_transport))
    return app
