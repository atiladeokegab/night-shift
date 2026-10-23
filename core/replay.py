"""The replayer: walks a match's Moments at `speed` (or, for a match with a video map, its mapped
moments ahead of time), asks the commentator for a Line per moment, stores each Line and publishes
moment, line and stats events for the SSE stream."""

import asyncio
import uuid
from collections.abc import Callable

from core.stats import stats


def moment_seconds(moment: dict) -> float:
    """Match time of a moment: football "mm:ss"; cricket "over.ball" at 30 s a ball."""
    clock = str(moment.get("clock", "0"))
    if moment.get("sport") == "football":
        mm, _, ss = clock.partition(":")
        return int(mm) * 60 + int(ss or 0)
    over, _, ball = clock.partition(".")
    # shortcut: Cricsheet has no ball timestamps, so 30 s a ball; real times if a feed gives them.
    return (int(over) * 6 + int(ball or 0)) * 30.0


class Replay:
    def __init__(self, match_id: str, speed: float):
        self.id = uuid.uuid4().hex[:12]
        self.match_id = match_id
        self.speed = speed
        self.events: list[dict] = []
        self.done = False
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
            await replay.publish("line", line)
            await replay.publish("stats", stats(store))
    except Exception as exc:  # the stream says why it stopped instead of hanging open
        await replay.publish("error", {"detail": str(exc)})
    finally:
        await replay.finish()
