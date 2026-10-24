"""#353: a match with no video waits out its match-time gaps at the replay's speed, but never more
than MAX_GAP_S, so Orlando (7457), the wall's first tile, is not silent for a minute after its
second line. Every moment is still called."""

import asyncio
import uuid

from core import replay as replay_mod
from core.replay import MAX_GAP_S, Replay, moment_seconds, run_replay
from core.store import Store
from data.matches import load_moments

ORLANDO = "7457"


def test_no_video_gaps_are_capped_and_every_moment_is_called(tmp_path, monkeypatch):
    moments = load_moments(ORLANDO)[:3]
    assert (moment_seconds(moments[2]) - moment_seconds(moments[1])) / 4 > 60  # the 62 s silence
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    monkeypatch.setattr(replay_mod.asyncio, "sleep", sleep)

    def commentate(m, history):
        return {
            "line_id": uuid.uuid4().hex,
            "match_id": ORLANDO,
            "moment_idx": m["idx"],
            "text": "A shot.",
        }

    r = Replay(ORLANDO, 4)
    asyncio.run(run_replay(r, moments, commentate, Store(str(tmp_path))))
    assert [e["data"]["idx"] for e in r.events if e["event"] == "moment"] == [
        m["idx"] for m in moments
    ]
    assert slept and max(slept) == MAX_GAP_S
    assert (
        slept[0] == (moment_seconds(moments[1]) - moment_seconds(moments[0])) / 4
    )  # a short gap is kept
