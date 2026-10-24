"""Cost per match (#174): what one full replay spent, model plus voice, from the store only."""

import asyncio

from core.replay import Replay, run_replay
from core.store import Store

MOMENTS = [
    {"sport": "football", "match_id": "f1", "idx": i, "clock": clock, "type": "Shot"}
    for i, clock in enumerate(["03:10", "41:02"])
]
VIDEO = {
    "youtube_id": "abcdefghijk",
    "moments": [{"idx": 0, "video_t": 5.0}, {"idx": 1, "video_t": 9.0}],
}


def commentate(moment, history):
    return {"line_id": f"f1-{moment['idx']}", "text": "Shot!", "model": "claude-haiku-4-5"}


def test_a_full_replay_tags_its_lines_and_voice_and_is_stored_as_a_match(tmp_path):
    store, spoken = Store(tmp_path), []
    replay = Replay("f1", speed=1.0)
    speak = lambda line, moment, at: spoken.append(line["replay_id"])  # noqa: E731
    asyncio.run(run_replay(replay, MOMENTS, commentate, store, VIDEO, speak))
    assert [ln["replay_id"] for ln in store.all("lines")] == [replay.id] * 2
    assert spoken == [replay.id] * 2
    assert store.all("replays") == [{"replay_id": replay.id, "match_id": "f1"}]


def test_a_jump_is_not_a_match(tmp_path):
    store = Store(tmp_path)
    asyncio.run(run_replay(Replay("f1", speed=1.0), MOMENTS, commentate, store, VIDEO, None, 1))
    assert store.all("replays") == []
