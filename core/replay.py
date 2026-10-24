"""The replayer: walks a match's Moments at `speed` (or, for a match with a video map, its mapped
moments ahead of time), asks the commentator for a Line per moment, stores each Line and publishes
moment, line and stats events for the SSE stream."""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable

from core.stats import stats

log = logging.getLogger("night_shift.replay")


def moment_seconds(moment: dict) -> float:
    """Match time of a moment: football and f1 "mm:ss"; basketball "mm:ss" left in a 12-minute
    quarter (5-minute overtimes); cricket "over.ball" at 30 s a ball."""
    clock = str(moment.get("clock", "0"))
    if moment.get("sport") in ("football", "f1"):
        mm, _, ss = clock.partition(":")
        return int(mm) * 60 + int(ss or 0)
    if moment.get("sport") == "basketball":
        mm, _, ss = clock.partition(":")
        period = int(moment.get("period") or 1)
        length = 720 if period <= 4 else 300
        start = 720 * min(period - 1, 4) + 300 * max(period - 5, 0)
        return start + length - (int(mm) * 60 + int(ss or 0))
    over, _, ball = clock.partition(".")
    # shortcut: Cricsheet has no ball timestamps, so 30 s a ball; real times if a feed gives them.
    return (int(over) * 6 + int(ball or 0)) * 30.0


class Replay:
    def __init__(self, match_id: str, speed: float):
        self.id = uuid.uuid4().hex[:12]
        self.match_id = match_id
        self.speed = speed
        self.started = time.monotonic()
        self.events: list[dict] = []
        self.done = False
        self.listeners = 0  # open streams; none for REJOIN_S stops the replay (core/app.py)
        self.stopping: asyncio.TimerHandle | None = None  # that stop, until a stream opens
        self._changed = asyncio.Condition()

    async def publish(self, event: str, data: dict) -> None:
        async with self._changed:
            self.events.append({"event": event, "data": data})
            self._changed.notify_all()

    async def finish(self) -> None:
        async with self._changed:
            self.done = True
            self._changed.notify_all()

    async def follow(self):
        """Every event from the start, then each new one as it lands, until the replay ends."""
        i = 0
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda i=i: i < len(self.events) or self.done)
                batch, done = self.events[i:], self.done
            for event in batch:
                yield event
            i += len(batch)
            if done and i == len(self.events):
                return


async def run_replay(
    replay: Replay,
    moments: list[dict],
    commentate: Callable[[dict, list[dict]], dict],
    store,
    video: dict | None = None,
    speak: Callable[[dict, dict, float | None], None] | None = None,
) -> None:
    # A video map: only mapped moments are called, each tagged with its video time and sent as
    # soon as it is ready; the page holds each line until the player reaches that time.
    video_t = {m["idx"]: m["video_t"] for m in video["moments"]} if video else None
    try:
        last = None
        history: list[dict] = []
        for moment in moments:
            tag = {}
            if video_t is None:
                at = moment_seconds(moment)
                if last is not None and at > last:
                    await asyncio.sleep((at - last) / replay.speed)
                last = at
            elif moment["idx"] in video_t:
                tag = {"video_t": video_t[moment["idx"]]}
            else:  # not in the video: no call, but still recent play for later lines
                history.append(moment)
                continue
            await replay.publish("moment", {**moment, **tag})
            # commentate sees only moments up to this one: later events never reach the model
            line = await asyncio.to_thread(commentate, moment, list(history))
            history.append(moment)
            if line is None:  # the commentator had nothing usable to say: the moment stays silent
                continue
            line = {**line, **tag}
            store.append("lines", line)
            # shortcut: due as if the video starts with the replay at its `start` second;
            # the player's own clock if the page ever sends it.
            if speak:
                due = replay.started + tag["video_t"] - video.get("start", 0) if tag else None
                speak(line, moment, due)
            await replay.publish("line", line)
            await replay.publish("stats", stats(store))
    except Exception as exc:  # the stream says why it stopped instead of hanging open
        # the provider's status and error type, e.g. Mubit's 402 when its credit runs out
        name = type(exc).__name__
        log.warning("replay %s stopped: %s: %s", replay.match_id, name, str(exc)[:300])
        # never the provider's text: it can carry its console URL and request id onto the screen
        off_air = {"code": "commentator_off_air", "detail": "Commentator is off air for a moment"}
        await replay.publish("error", off_air)
    finally:
        await replay.finish()
