"""The replayer: walks a match's Moments at `speed` (or, for a match with a video map, its mapped
moments ahead of time), asks the commentator for a Line per moment, and with a video map for stat
lines in the quiet stretches between them (core/insight.py), stores each Line and publishes
moment, line and stats events for the SSE stream."""

import asyncio
import itertools
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from core import insight
from core.stats import stats

log = logging.getLogger("night_shift.replay")
# never the provider's text: it can carry its console URL and request id onto the screen
OFF_AIR = "Commentator is off air for a moment"


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


async def auto_fix(store, correct, rejected: dict, kept: dict) -> None:
    """The number check's rejected first try, corrected to the kept retry as a Fix that is visibly
    not a human's: the try was recorded before the check could see it."""
    try:
        sent = await asyncio.to_thread(correct, rejected, kept["text"])
    except Exception as exc:  # the kept line is already said; only the correction is lost
        log.warning("auto fix for %s not sent: %s", rejected.get("line_id"), str(exc)[:300])
        return
    await asyncio.to_thread(
        store.append,
        "auto_fixes",  # never in `fixes`: those are the people's, and the review queue's "fixed"
        {
            "line_id": rejected["line_id"],
            "corrected_text": kept["text"],
            "reason": "auto: number check",
            "auto": True,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mubit_request_id": sent["mubit_request_id"],
            "reply_matched": sent["reply_matched"],
            "recorded": sent.get("recorded", False),
        },
    )


async def run_replay(
    replay: Replay,
    moments: list[dict],
    commentate: Callable[[dict, list[dict]], dict],
    store,
    video: dict | None = None,
    speak: Callable[[dict, dict, float | None], None] | None = None,
    start_idx: int = 0,
    correct: Callable[[dict, str], dict] | None = None,
) -> None:
    # A video map: only mapped moments are called, each tagged with its video time and sent as
    # soon as it is ready; the page holds each line until the player reaches that time.
    video_t = {m["idx"]: m["video_t"] for m in video["moments"]} if video else None
    gaps = insight.Gaps(replay.match_id, store, replay.id) if video else None

    async def say(line: dict, moment: dict) -> None:
        # shortcut: due as if the video starts with the replay at its `start` second;
        # the player's own clock if the page ever sends it.
        if speak:
            due = replay.started + line["video_t"] - video.get("start", 0) if video else None
            # this replay's id, so a cached line spoken again is charged to the replay that spoke it
            speak({**line, "replay_id": replay.id}, moment, due)
        await replay.publish("line", line)
        await replay.publish("stats", stats(store))

    fixes: list[asyncio.Task] = []
    try:
        last = None
        history: list[dict] = []
        # the texts said so far: a stat line that nearly repeats one of the last few is dropped;
        # a moment's own line is news, so it is always said
        recent: list[str] = []
        # a jump (#163): earlier play is on screen from the start, its score and clock and the lines
        # already said for it, untimed so nothing waits for the picture; it is never called again
        if start_idx:
            said = {
                ln["moment_idx"]: ln
                for ln in await asyncio.to_thread(store.all, "lines")
                # the moment's own line, not the lead's later reply to the analyst at its idx
                if ln.get("match_id") == replay.match_id
                and ln.get("speaker", "lead") == "lead"
                and "reply" not in ln
            }
            fixed = {f["line_id"]: f for f in await asyncio.to_thread(store.all, "fixes")}
            for moment in moments:
                if moment["idx"] < start_idx:
                    await replay.publish("moment", moment)
                    if moment["idx"] in said:
                        old = {k: v for k, v in said[moment["idx"]].items() if k != "video_t"}
                        await replay.publish("line", {**old, "history": True})
                        if (
                            old["line_id"] in fixed
                        ):  # shown in its fixed wording, as when it was fixed
                            await replay.publish("fixed", fixed[old["line_id"]])
        for moment in moments:
            tag = {}
            if moment["idx"] < start_idx:  # a jump (#163): published above, never called
                history.append(moment)
                continue
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
            line = await asyncio.to_thread(insight.checked, commentate, moment, list(history))
            history.append(moment)
            if line is not None:  # None: the commentator had nothing usable to say
                rejected = line.pop("rejected", None)
                said_line = {**line, **tag, "speaker": "lead", "replay_id": replay.id}
                await say(store.append("lines", said_line), moment)
                recent.append(line.get("text") or "")
                if rejected and correct:  # after the kept line is out: never on its path
                    fixes.append(asyncio.create_task(auto_fix(store, correct, rejected, line)))
            if not tag:
                continue
            # the quiet stretch until the next mapped moment: stat lines, each due once the
            # last line has likely been spoken
            end = min((t for t in video_t.values() if t > tag["video_t"]), default=None)
            t, said = tag["video_t"], (line or {}).get("text")
            for n in itertools.count():
                t = insight.due_after(t, said)
                if end is None or t > end - insight.CLEAR_S:
                    break
                got = await asyncio.to_thread(
                    gaps.line, list(history), n, t, commentate, said, list(recent)
                )
                if got is None:
                    break
                stat, said_line = got
                await replay.publish("moment", {**stat, "video_t": t})
                await say({**said_line, "video_t": t}, stat)
                said = said_line["text"]
                recent.append(said)
        if not start_idx:  # played from kick-off to its last moment: a match for cost per match
            store.append("replays", {"replay_id": replay.id, "match_id": replay.match_id})
    except Exception as exc:  # the stream says why it stopped instead of hanging open
        # the provider's status and error type, e.g. Mubit's 402 when its credit runs out
        name = type(exc).__name__
        log.warning("replay %s stopped: %s: %s", replay.match_id, name, str(exc)[:300])
        off_air = {"code": "commentator_off_air", "detail": OFF_AIR}
        await replay.publish("error", off_air)
    finally:
        await asyncio.gather(*fixes, return_exceptions=True)
        await replay.finish()
