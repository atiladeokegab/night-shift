"""The app factory: every route of the spine. The match catalogue, the Moment loader and the
commentator come from data/ and agent/ (#13) through `Deps`, so tests inject their own."""

import asyncio
import json
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
from core.voice import voice_router

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
        video = d.video_map(req.match_id)
        task = asyncio.create_task(run_replay(replay, moments, d.commentate, store, video))
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

    app.include_router(voice_router(store, tts_transport))
    # the built page (web/, #18) at /, mounted last so every API route above wins
    if WEB.is_dir():
        app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    return app
