"""Jump to the big moment (#163): POST /replays {start_idx} starts the stream at that moment, with
nothing before it called, and a finished replay still answers questions."""

import time

import pytest
from fastapi.testclient import TestClient

import core.app as core_app
from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments, video_map

KOBE = "0020500591"
LONG = [  # a timed match: a minute between moments, so moment 50 is 50 minutes in at speed 1
    {"sport": "football", "match_id": "long", "idx": i, "clock": f"{i:02d}:00", "type": "Shot"}
    for i in range(60)
]


def recording(called: list):
    def commentate(moment, history):
        called.append((moment["idx"], [h["idx"] for h in history]))
        n = len(called)
        return {
            "line_id": f"{moment['match_id']}-{n}",
            "moment_idx": moment["idx"],
            "text": "Shot!",
        }

    return commentate


def first_line_s(client, match_id: str, start_idx: int) -> float:
    began = time.monotonic()
    body = {"match_id": match_id, "speed": 1, "start_idx": start_idx}
    rid = client.post("/replays", json=body).json()["replay_id"]
    with client.stream("GET", f"/replays/{rid}/stream") as stream:
        for row in stream.iter_lines():
            if row == "event: line":
                return time.monotonic() - began
    raise AssertionError("no line")


@pytest.mark.parametrize("match_id", ["long", KOBE])
def test_a_replay_started_at_a_moment_streams_its_first_line_within_3_s(tmp_path, match_id):
    called = []
    moments = {"long": LONG}.get(match_id) or load_moments(match_id)
    vmap = video_map if match_id == KOBE else (lambda mid, start_idx=None: None)
    deps = Deps(list_matches, lambda mid: moments, recording(called), vmap)
    with TestClient(create_app(Store(tmp_path), deps)) as client:
        assert first_line_s(client, match_id, 50 if match_id == "long" else 22) < 3
    first, history = called[0]
    assert first == (50 if match_id == "long" else 22)  # nothing before it was called
    assert history == list(range(first))  # but the commentator knows what came before


def test_a_jump_publishes_nothing_before_its_moment_and_refuses_an_unknown_one(tmp_path):
    deps = Deps(lambda: [], lambda mid: LONG[:5], recording([]))
    with TestClient(create_app(Store(tmp_path), deps)) as client:
        rid = client.post("/replays", json={"match_id": "long", "speed": 1e6, "start_idx": 3})
        events = read_stream(client, rid.json()["replay_id"])
        assert [d["idx"] for n, d in events if n == "moment"] == [3, 4]
        assert client.post("/replays", json={"match_id": "long", "start_idx": 9}).status_code == 422
        assert (
            client.post("/replays", json={"match_id": "long", "start_idx": -1}).status_code == 422
        )


def test_every_match_lists_its_peak_and_the_video_second_its_jump_starts_at():
    matches = {m["match_id"]: m for m in list_matches()}
    assert all("peak_idx" in m for m in matches.values())
    kobe = matches[KOBE]
    eighty = next(m for m in video_map(KOBE)["moments"] if m["idx"] == kobe["peak_idx"])
    assert kobe["peak_video_start"] == int(eighty["video_t"]) - 10  # the usual 10 s lead-in
    assert video_map(KOBE, kobe["peak_idx"])["start"] == kobe["peak_video_start"]


def test_a_finished_replay_still_answers_questions_after_its_stream_closes(tmp_path, monkeypatch):
    monkeypatch.setattr(core_app, "REJOIN_S", 0.05)

    def ask(question, past, lines):
        return {"line_id": "a1", "moment_idx": past[-1]["idx"], "question": question, "text": "3-0"}

    deps = Deps(lambda: [], lambda mid: LONG[:3], recording([]), ask=ask)
    with TestClient(create_app(Store(tmp_path), deps)) as client:
        rid = client.post("/replays", json={"match_id": "long", "speed": 1e6, "start_idx": 1})
        rid = rid.json()["replay_id"]
        read_stream(client, rid)  # to the end
        time.sleep(0.2)  # the stream is closed and REJOIN_S has passed
        res = client.post(f"/replays/{rid}/ask", json={"question": "Score?"})
        assert res.status_code == 200 and res.json()["text"] == "3-0"
