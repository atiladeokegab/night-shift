"""Let them watch (#291): a note of the viewer's shared screen goes in the next line's user message,
never the system prompt or tools, so the lead's Mubit task stays the same."""

import logging
import threading

import pytest
from fastapi.testclient import TestClient

from agent import look
from agent.commentator import build_request
from core.app import Deps, create_app
from core.guard import spent
from core.look import Looks
from core.smoke import read_stream
from core.store import Store
from data.matches import load_moments, match_header

JAZZ = "0049700088"
NOTE = "a replay of the dunk from behind the basket"


def request_at(idx, seen=None, stat=False):
    moments = load_moments(JAZZ)[: idx + 1]
    if stat:
        moments[-1] = {**moments[-1], "type": "Stat"}
    return build_request(match_header(JAZZ), moments, (), seen)


def test_a_note_goes_at_the_end_of_the_user_message_only():
    for stat in (False, True):
        plain, seen = request_at(33, stat=stat), request_at(33, NOTE, stat)
        said = seen["messages"][0]["content"]
        assert said == plain["messages"][0]["content"] + f"\nOn screen: {NOTE}"
        # byte-identical: the system prompt, tools, model and everything else
        assert {**seen, "messages": None} == {**plain, "messages": None}
        assert NOTE not in seen["system"]


def test_no_note_leaves_the_request_as_it_was():
    assert request_at(33, None) == request_at(33, "") == request_at(33)


# The route: POST /replays/{id}/look, with the vision call mocked

FRAME = "/9j/" + "Q" * 400  # a base64 JPEG's shape; the mocked call never decodes it


def moment(idx, players=None):
    return {
        "sport": "football",
        "match_id": "7",
        "idx": idx,
        "period": 1,
        "clock": f"{idx:02d}:00",
        "type": "Shot",
        "team": "Reds",
        "players": players or {},
        "outcome": "Saved",
        "score": {"home": 0, "away": 0},
        "detail": {},
    }


MOMENTS = [moment(0, {"shooter": "Kylian Mbappé"}), moment(1), moment(2)]
DUE = [(0, 5.0), (1, 12.0), (2, 60.0)]  # each moment's time on the video


class Eyes:
    """The vision model, mocked: says `said` and keeps each request it is sent."""

    def __init__(self, said):
        self.said, self.requests = said, []

    def call(self, request):
        self.requests.append(request)
        if isinstance(self.said, Exception):
            raise self.said
        usage = {"input_tokens": 1000, "output_tokens": 10}
        return {"content": [{"type": "text", "text": self.said}], "usage": usage}


class Gate(threading.Event):
    """Set, the replay goes on from moment 0; `held` is set once moment 0's line is being called."""

    def __init__(self):
        super().__init__()
        self.held = threading.Event()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def watched(tmp_path, said, env=None):
    """An app whose replay of match 7 holds at moment 0 until `go` is set, and the `seen` each
    line's commentate was given."""
    go, seen, eyes, clock = Gate(), [], Eyes(said), Clock()

    def commentate(m, history, **kw):
        seen.append((m["idx"], m["type"], kw.get("seen")))
        if m["idx"] == 0:
            go.held.set()
            go.wait(5)
        return {"line_id": f"l{m['idx']}", "match_id": "7", "moment_idx": m["idx"], "text": "New"}

    def see(image, names):
        return look.see(image, names, provider=eyes)

    video = {"youtube_id": "x", "start": 0, "moments": [{"idx": i, "video_t": t} for i, t in DUE]}
    deps = Deps(lambda: [], lambda mid: MOMENTS, commentate, lambda *a: video, look=see)
    looks = Looks(env or {}, clock)
    client = TestClient(create_app(store=Store(tmp_path), deps=deps, looks=looks))
    return client, go, seen, eyes, clock


def frame(client, replay_id, image=FRAME, t=12.5):
    return client.post(f"/replays/{replay_id}/look", json={"image": image, "t": t})


def started(client):
    return client.post("/replays", json={"match_id": "7", "speed": 1e6}).json()["replay_id"]


def test_a_frames_note_goes_in_the_next_line_once_digits_stripped(tmp_path):
    client, go, seen, eyes, _ = watched(tmp_path, "Players celebrate the 2-1 goal at 45:00")
    with client:
        rid = started(client)
        assert go.held.wait(5)
        got = frame(client, rid)
        go.set()
        read_stream(client, rid)
    assert got.status_code == 200 and got.json() == {"note": "players celebrate the goal at"}
    notes = [(idx, note) for idx, _, note in seen if note]
    # once, by the first line called after the frame within 15 s of it on the video (moment 0's
    # quiet-stretch line at 5 s, or moment 1 at 12 s), never moment 2 at 60 s
    assert len(notes) == 1 and notes[0] in (
        (0, "players celebrate the goal at"),
        (1, "players celebrate the goal at"),
    )
    assert seen[0] == (0, "Shot", None)  # called before the frame
    sent = eyes.requests[0]
    assert sent["system"] == look.SYSTEM and "tools" not in sent
    assert sent["messages"][0]["content"][0]["source"]["data"] == FRAME


def test_a_note_that_names_anyone_is_dropped(tmp_path):
    names = ["Kylian Mbappé", "Mbappe", "Reds"]
    for said in (
        "A close-up of Mbappe",
        "a close-up of mbappé",
        "Reds fans",
        "The crowd and Messi",
    ):
        assert look.clean(said, names) is None, said
    client, go, seen, _, _ = watched(tmp_path, "a close-up of kylian")  # a player of match 7
    with client:
        rid = started(client)
        got = frame(client, rid)
        go.set()
        read_stream(client, rid)
    assert got.json() == {"note": None} and {note for *_, note in seen} == {None}


def test_numbers_in_words_and_nothing_are_no_note():
    assert look.clean("Two players argue") is None
    assert look.clean("nothing") is None and look.clean("") is None
    assert look.clean("the ball near the box.") == "the ball near the box"


def test_ordinals_amounts_other_scripts_and_capitals_are_no_note():
    probes = ["sixth goal", "the twentieth corner", "a dozen shots", "a thousand fans", "half-time"]
    probes += ["²", "a ½ volley", "LEBRON", "a dunk by LEBRON"]
    for said in probes:
        assert look.clean(said) is None, said
    assert look.clean("a corner kick") == "a corner kick"


def test_one_frame_every_four_seconds_then_the_cap(tmp_path):
    client, go, _, eyes, clock = watched(tmp_path, "a corner kick", {"LOOKS_PER_REPLAY": "2"})
    with client:
        rid = started(client)
        first, soon = frame(client, rid), frame(client, rid)
        clock.now += 4
        second = frame(client, rid)
        clock.now += 4
        over = frame(client, rid)
        go.set()
        read_stream(client, rid)
        ended = frame(client, rid)
    assert first.status_code == 200 and second.status_code == 200
    assert soon.status_code == 429 and 1 <= int(soon.headers["retry-after"]) <= 4
    assert over.status_code == 410 and ended.status_code == 410
    assert len(eyes.requests) == 2  # a refused frame costs no call


def test_a_note_never_goes_in_a_line_far_from_its_frame_on_the_video(tmp_path):
    # the replay calls its lines ahead of the picture: a frame at 40 s is of no line's moment
    client, go, seen, _, _ = watched(tmp_path, "a replay")
    with client:
        rid = started(client)
        assert frame(client, rid, t=40).json() == {"note": "a replay"}
        go.set()
        read_stream(client, rid)
    assert {note for *_, note in seen} == {None}


def test_a_note_older_than_ten_seconds_is_not_used(tmp_path):
    client, go, seen, _, clock = watched(tmp_path, "a replay")
    with client:
        rid = started(client)
        assert go.held.wait(5)  # moment 0 is called before the frame
        frame(client, rid)
        clock.now += 11
        go.set()
        read_stream(client, rid)
    assert {note for *_, note in seen} == {None}


def test_a_frame_is_never_stored_or_logged(tmp_path, caplog):
    secret = "/9j/" + "Z" * 396 + "SECRET=="
    client, go, _, _, _ = watched(tmp_path, RuntimeError(f"bad image {secret}"))
    caplog.set_level(logging.DEBUG)
    with client:
        rid = started(client)
        got = frame(client, rid, secret)
        go.set()
        read_stream(client, rid)
    assert got.status_code == 200 and got.json() == {"note": None}  # a failed call: no note
    assert "SECRET" not in caplog.text and "ZZZZ" not in caplog.text
    on_disk = "".join(p.read_text(errors="ignore") for p in tmp_path.rglob("*") if p.is_file())
    assert "ZZZZ" not in on_disk


def test_only_a_base64_jpeg_frame_is_taken(tmp_path):
    client, go, _, eyes, _ = watched(tmp_path, "a replay")
    with client:
        rid = started(client)
        png = frame(client, rid, "iVBORw0KGgo" + "A" * 200)
        junk = frame(client, rid, "/9j/" + "<script>" * 30)
        go.set()
        read_stream(client, rid)
    assert png.status_code == 422 and junk.status_code == 422 and eyes.requests == []


def test_each_frame_call_counts_toward_the_daily_spend(tmp_path):
    client, go, _, _, clock = watched(tmp_path, "a corner kick")
    with client:
        rid = started(client)
        frame(client, rid)
        clock.now += 4
        frame(client, rid)
        go.set()
        read_stream(client, rid)
    calls = Store(tmp_path).all("looks")
    assert [(c["model"], c["tokens_in"], c["tokens_out"]) for c in calls] == [
        (look.MODEL, 1000, 10)
    ] * 2
    day = calls[0]["created_at"][:10]
    assert spent(Store(tmp_path), day) == pytest.approx(2 * (1000 * 1.0 + 10 * 5.0) / 1e6)


def test_a_frame_body_over_the_limit_is_refused_before_it_is_read(tmp_path):
    client, go, _, eyes, _ = watched(tmp_path, "a corner kick")
    big = b'{"image": "/9j/' + b"A" * 430_000 + b'", "t": 1}'
    with client:
        rid = started(client)
        said = client.post(f"/replays/{rid}/look", content=big)  # its Content-Length
        hid = client.post(f"/replays/{rid}/look", content=iter([big[:200_000], big[200_000:]]))
        go.set()
        read_stream(client, rid)
    assert said.status_code == 413 and hid.status_code == 413 and eyes.requests == []


def test_offline_there_is_no_vision_call(monkeypatch):
    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    assert look.see(FRAME, []) == {"note": None}
