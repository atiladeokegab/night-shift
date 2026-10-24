"""Let them watch (#291): each replay's frame limits and its latest screen note. At most one frame
every EVERY_S seconds a replay and LOOKS_PER_REPLAY in all; a note is kept KEEP_S seconds and used
by one line. Only the note is held, in memory: never the frame."""

import math
import os
import time

EVERY_S = 4.0
KEEP_S = 10.0


class Looks:
    def __init__(self, env=os.environ, clock=time.monotonic):
        self.cap = int(env.get("LOOKS_PER_REPLAY") or 150)
        self.clock = clock
        self.sent: dict[str, tuple[float, int]] = {}  # replay id: (last frame at, frames so far)
        self.notes: dict[str, tuple[float, str]] = {}  # replay id: (seen at, note)

    def over(self, replay_id: str) -> bool:
        return bool(self.cap) and self.sent.get(replay_id, (0.0, 0))[1] >= self.cap

    def hit(self, replay_id: str) -> int:
        """0 and the frame counts, else the seconds until the replay may send the next one."""
        now, (last, n) = self.clock(), self.sent.get(replay_id, (-math.inf, 0))
        if now - last < EVERY_S:
            return max(1, math.ceil(last + EVERY_S - now))
        self.sent[replay_id] = (now, n + 1)
        return 0

    def keep(self, replay_id: str, note: str) -> None:
        self.notes[replay_id] = (self.clock(), note)

    def take(self, replay_id: str) -> str | None:
        """The replay's note if it is fresh, once: the next line gets it, the one after does not."""
        at, note = self.notes.pop(replay_id, (-math.inf, None))
        return note if self.clock() - at <= KEEP_S else None

    def forget(self, replay_id: str) -> None:
        self.sent.pop(replay_id, None)
        self.notes.pop(replay_id, None)
