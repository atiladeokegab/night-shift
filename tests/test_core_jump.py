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
            "match_id": moment["match_id"],
            "moment_idx": moment["idx"],
            "text": f"Call {n}.",
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


def test_a_jump_lands_with_the_score_clock_and_lines_already_at_its_moment(tmp_path):
    called = []
    store = Store(tmp_path)
    said = {"line_id": "old-21", "match_id": KOBE, "moment_idx": 21, "text": "Kobe steals it."}
    store.append("lines", {**said, "video_t": 1420.0, "speaker": "lead"})
    store.append("lines", {**said, "line_id": "x", "match_id": "other", "speaker": "lead"})
    deps = Deps(list_matches, load_moments, recording(called), video_map)
    with TestClient(create_app(store, deps)) as client:
        rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e6, "start_idx": 22})
        events = read_stream(client, rid.json()["replay_id"])
    first = next(i for i, (n, d) in enumerate(events) if n == "line" and not d.get("history"))
    before = [d for n, d in events[:first] if n == "moment"]
    assert [m["idx"] for m in before] == list(range(23))  # the history, then the jump's own moment
    # when the video starts, the stage already shows the play just before the jump: Q4 1:11, 120-102
    at_jump = before[-2]
    assert (at_jump["period"], at_jump["clock"], at_jump["score"]) == (
        4,
        "01:11",
        {"home": 120, "away": 102},
    )
    assert all(
        "video_t" not in m for m in before[:-1]
    )  # untimed: on screen before the picture moves
    old = [d for n, d in events[:first] if n == "line"]
    assert [(ln["line_id"], ln["history"], "video_t" in ln) for ln in old] == [
        ("old-21", True, False)
    ]
    assert (
        called[0][0] == 22 and events[first][1]["moment_idx"] == 22
    )  # nothing before it is called


def test_a_jump_shows_each_earlier_line_once_however_often_the_match_was_replayed(tmp_path):
    store = Store(tmp_path)
    for run in range(2):  # two earlier replays both called moments 18 to 21
        for idx in range(18, 22):
            line = {"line_id": f"r{run}-{idx}", "match_id": KOBE, "moment_idx": idx}
            store.append("lines", {**line, "text": f"Run {run}, moment {idx}.", "speaker": "lead"})
    deps = Deps(list_matches, load_moments, recording([]), video_map)
    with TestClient(create_app(store, deps)) as client:
        rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e6, "start_idx": 22})
        lines = [d for n, d in read_stream(client, rid.json()["replay_id"]) if n == "line"]
    old = [ln["line_id"] for ln in lines if ln.get("history")]
    assert old == ["r1-18", "r1-19", "r1-20", "r1-21"]  # the latest replay's line, once per moment
    assert len({ln["line_id"] for ln in lines}) == len(lines)
    assert len({ln["text"] for ln in lines}) == len(lines)


def test_a_jump_shows_an_earlier_line_in_its_fixed_wording(tmp_path):
    def correct(line, text, **kw):
        return {"mubit_request_id": "m1", "reply_matched": True}

    deps = Deps(list_matches, load_moments, recording([]), video_map, correct=correct)
    with TestClient(create_app(Store(tmp_path), deps)) as client:
        rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e6}).json()["replay_id"]
        first = [d for n, d in read_stream(client, rid) if n == "line" and d["moment_idx"] == 20][0]
        fix = {"corrected_text": "Kobe makes it 120.", "reason": "wording"}
        assert client.post(f"/lines/{first['line_id']}/fix", json=fix).status_code == 200
        rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e6, "start_idx": 22})
        events = read_stream(client, rid.json()["replay_id"])
    at = next(
        i for i, (n, d) in enumerate(events) if n == "line" and d["line_id"] == first["line_id"]
    )
    assert events[at][1]["history"] and events[at + 1][0] == "fixed"
    assert events[at + 1][1]["corrected_text"] == "Kobe makes it 120."


def test_a_jump_to_an_unknown_moment_is_refused(tmp_path):
    deps = Deps(lambda: [], lambda mid: LONG[:5], recording([]))
    with TestClient(create_app(Store(tmp_path), deps)) as client:
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
