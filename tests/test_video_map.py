"""A-6.4@2, server side: a match with a video map calls only its mapped moments, tags each with
`video_t` and sends them ahead of time; a match without one keeps the wall-clock pacing."""

import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.replay import Replay, run_replay
from core.smoke import read_stream
from core.store import Store
from data.matches import VIDEO, list_matches, load_moments, video_map

MOMENTS = [
    {"sport": "football", "match_id": "f1", "idx": i, "clock": clock, "type": "Shot"}
    for i, clock in enumerate(["03:10", "41:02", "88:00"])
]
F1_VIDEO = {
    "youtube_id": "abcdefghijk",
    "source": "test",
    "moments": [{"idx": 0, "video_t": 12.5}, {"idx": 2, "video_t": 80.0}],
}


def commentate(moment, history):
    assert "video_t" not in moment  # the model sees the Moment, never the video time
    assert all(h["idx"] < moment["idx"] for h in history)
    return {
        "line_id": f"f1-{moment['idx']}",
        "text": "Shot!",
        "latency_ms": 100,
        "first_word_ms": 50,
        "tokens_in": 10,
        "tokens_out": 5,
        "mubit_request_ids": [f"r{moment['idx']}"],
    }


def stream(tmp_path, video):
    deps = Deps(lambda: [], lambda mid: MOMENTS, commentate, lambda mid: video)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()["replay_id"]
        return read_stream(client, rid)


def test_mapped_match_calls_only_mapped_moments_with_their_video_time(tmp_path):
    events = stream(tmp_path, F1_VIDEO)
    opening = sum(n == "line" and "open" in d for n, d in events)  # the cold open (#221) first
    assert [n for n, _ in events] == ["moment", "line", "stats"] * (opening + 2) + ["end"]
    lines = [d for n, d in events if n == "line" and "open" not in d]
    moments = [d for n, d in events if n == "moment" and d["type"] != "Stat"]
    assert [(ln["line_id"], ln["video_t"]) for ln in lines] == [("f1-0", 12.5), ("f1-2", 80.0)]
    assert [m["video_t"] for m in moments] == [12.5, 80.0]


def test_unmapped_match_is_unchanged(tmp_path):
    events = stream(tmp_path, None)
    lines = [d for n, d in events if n == "line"]
    assert [ln["line_id"] for ln in lines] == ["f1-0", "f1-1", "f1-2"]
    assert not any("video_t" in d for _, d in events)


async def replay_within(seconds, video, store):
    replay = Replay("f1", speed=1e-9)  # paced by the match clock, this would take ~forever
    await asyncio.wait_for(run_replay(replay, MOMENTS, commentate, store, video), seconds)
    return [e for e in replay.events if e["event"] == "line"]


def test_mapped_lines_never_wait_for_wall_clock(tmp_path):
    lines = asyncio.run(replay_within(5, F1_VIDEO, Store(tmp_path)))
    assert len([e for e in lines if "open" not in e["data"]]) == 2


def test_unmapped_replay_still_paces_by_the_match_clock(tmp_path):
    with pytest.raises(TimeoutError):
        asyncio.run(replay_within(0.5, None, Store(tmp_path)))


MAPS = sorted(VIDEO.glob("*.json"))


def test_every_demo_match_has_a_map():
    assert {p.stem for p in MAPS} == {
        "football-3754092",
        "cricket-1298150",
        "football-3869685",
        "football-3913122",
        "basketball-0049700088",
        "basketball-0020500591",
        "f1-9636",
    }
    assert {m["match_id"]: m.get("youtube_id") for m in list_matches()} == {
        "3754092": "w0ORwSCI7Cs",
        "1298150": "tz_5DAA6IgE",
        "3869685": "VfmQIyDggBU",
        "3913122": "soJej-DhVe0",
        "0049700088": "kwAu78IiixE",
        "0020500591": "46nYnjGdQlk",
        "9636": "ctd_8sQbF_I",
    }


def test_only_the_embed_blocked_videos_say_so():
    # Every demo video embeds; a blocked one would get a poster and a YouTube link instead.
    assert {m["match_id"]: m.get("embed") for m in list_matches()} == {
        "3754092": None,
        "1298150": None,
        "3869685": None,
        "3913122": None,
        "0049700088": None,
        "0020500591": None,
        "9636": None,
    }


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.stem)
def test_map_file_validates_against_the_picker(path):
    sport, match_id = path.stem.split("-")
    vmap = video_map(match_id)
    assert re.fullmatch(r"[A-Za-z0-9_-]{11}", vmap["youtube_id"]) and vmap["source"]
    picked = {m["idx"]: m for m in load_moments(match_id)}
    idxs = [m["idx"] for m in vmap["moments"]]
    times = [m["video_t"] for m in vmap["moments"]]
    assert idxs and all(i in picked and picked[i]["sport"] == sport for i in idxs)
    assert idxs == sorted(set(idxs)), "one entry per moment, in match order"
    assert all(a < b for a, b in zip(times, times[1:], strict=False)), "video times must increase"
    assert all(isinstance(t, (int, float)) and t >= 0 for t in times)


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.stem)
def test_demo_replay_streams_each_mapped_moment_once(tmp_path, path):
    match_id = path.stem.split("-")[1]
    deps = Deps(list_matches, load_moments, lambda m, h: {"line_id": str(m["idx"])}, video_map)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": match_id}).json()["replay_id"]
        lines = [d for n, d in read_stream(client, rid) if n == "line"]
    expected = [(str(m["idx"]), m["video_t"]) for m in video_map(match_id)["moments"]]
    assert [(ln["line_id"], ln["video_t"]) for ln in lines] == expected


def test_each_video_starts_12_s_before_its_first_mapped_moment():
    # Kobe's first call is 490 s into the highlights: the page starts the video at 478 s, not 0.
    # 10 s, not 5: the first line is ready ~2 s in, and v3 needs 2-3 s more (#57); 2 s more so the
    # two cold open lines fit (#221), and no longer, so no quiet is left after them (#297). A jump
    # keeps 10 s (tests/test_core_jump.py).
    assert {m["match_id"]: m.get("video_start") for m in list_matches()} == {
        "3754092": 0,
        "1298150": 0,
        "3869685": 69,
        "3913122": 27,
        "0049700088": 356,
        "0020500591": 478,
        "9636": 0,
    }


def test_line_audio_is_due_from_the_video_start(tmp_path):
    due = {}
    replay = Replay("f1", speed=1.0)
    video = {**F1_VIDEO, "start": 7}

    def speak(line, moment, at):
        if not any(k in line for k in ("open", "insight", "reply")):  # the moments' own lines
            due.setdefault(line["line_id"], at - replay.started)

    asyncio.run(run_replay(replay, MOMENTS, commentate, Store(tmp_path), video, speak))
    assert due == {"f1-0": pytest.approx(5.5), "f1-2": pytest.approx(73.0)}
