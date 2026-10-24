"""The fix loop (R-4): POST /lines/{id}/fix stores the fix beside the line, sends it as the next
turn of the line's own Mubit call, records reply_passed and marks the line fixed on the stream."""

import pytest
from fastapi.testclient import TestClient

from agent.commentator import FakeProvider, build_request, correct
from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import Store

MOMENTS = [{"sport": "football", "match_id": "f1", "idx": 0, "clock": "03:10", "type": "Shot"}]
LINE = {"line_id": "f1-0", "match_id": "f1", "moment_idx": 0, "text": "Shot!"}


def setup(tmp_path, correct_fn):
    store = Store(tmp_path)
    deps = Deps(lambda: [], lambda mid: MOMENTS, lambda m, h: dict(LINE), correct=correct_fn)
    return TestClient(create_app(store=store, deps=deps)), store


def test_fix_is_stored_sent_and_marks_the_line_fixed(tmp_path):
    sent = []

    def fake_correct(line, text, reason):
        sent.append((line["line_id"], text, reason))
        turn = "Producer correction: wrong"
        return {
            "mubit_request_id": "r-fix",
            "correction": turn,
            "reply_passed": True,
            "recorded": True,
        }

    client, store = setup(tmp_path, fake_correct)
    with client:
        replay_id = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()
        read_stream(client, replay_id["replay_id"])  # the replay has finished
        resp = client.post("/lines/f1-0/fix", json={"corrected_text": " Goal! ", "reason": "wrong"})
        events = read_stream(client, replay_id["replay_id"])
        stats = client.get("/stats").json()
    fix = resp.json()
    assert resp.status_code == 200
    assert sent == [("f1-0", "Goal!", "wrong")]
    assert {k: fix[k] for k in ("line_id", "corrected_text", "reason")} == {
        "line_id": "f1-0",
        "corrected_text": "Goal!",
        "reason": "wrong",
    }
    assert fix["mubit_request_id"] == "r-fix" and fix["reply_passed"] is True and fix["created_at"]
    assert fix["correction"] == "Producer correction: wrong"  # what Mubit was given (#245)
    assert fix["recorded"] is True  # #161: only a recorded fix counts toward the next adapter
    assert store.all("fixes") == [fix] and store.all("lines")[0]["text"] == "Shot!"
    assert ("fixed", fix) in events and stats["fixes"] == 1


def test_unknown_line_404_blank_fix_422(tmp_path):
    client, store = setup(tmp_path, lambda line, text: {})
    with client:
        store.append("lines", dict(LINE))
        assert client.post("/lines/nope/fix", json={"corrected_text": "x"}).status_code == 404
        assert client.post("/lines/f1-0/fix", json={"corrected_text": "  "}).status_code == 422


def test_a_failed_send_stores_nothing(tmp_path):
    def down(line, text):
        raise ConnectionError("mubit down")

    client, store = setup(tmp_path, down)
    with client:
        store.append("lines", dict(LINE))
        assert client.post("/lines/f1-0/fix", json={"corrected_text": "Goal!"}).status_code == 503
    assert store.all("fixes") == []


HEADER = {
    "sport": "football",
    "match_id": "7",
    "home": "Reds",
    "away": "Blues",
    "competition": "Cup",
    "stage": "Final",
    "date": "2020-01-01",
}


def moment(idx):
    return {
        "sport": "football",
        "match_id": "7",
        "idx": idx,
        "period": 1,
        "clock": f"{idx:02d}:00",
        "type": "Shot",
        "team": "Reds",
        "players": {"shooter": "Ann"},
        "outcome": "Saved",
        "score": {"home": 0, "away": 0},
        "detail": {},
    }


class Says(FakeProvider):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def call(self, request):
        reply = super().call(request)
        return {**reply, "content": [{"type": "text", "text": self.text}]}


@pytest.mark.parametrize(("said", "passed"), [(None, True), ("Ann scores! Reds lead 1-0.", False)])
def test_correction_is_the_next_turn_of_the_same_task_and_session(said, passed):
    moments = [moment(0), moment(1), moment(2)]
    provider = FakeProvider() if said is None else Says(said)
    line = {"match_id": "7", "moment_idx": 1, "text": "Ann scores!"}
    out = correct(line, "Ann's shot is saved!", HEADER, moments, provider, reason="Wrong event")
    original = build_request(HEADER, moments[:2])  # a later moment never reaches the model
    request = provider.requests[-1]
    assert {k: v for k, v in request.items() if k != "messages"} == {
        k: v for k, v in original.items() if k != "messages"
    }
    # #245: what was wrong, the facts and the producer's line; the provider writes the fix itself
    turn = (
        "Producer correction: Wrong event\n"
        "The facts at this moment. Score: Reds 0, Blues 0. Leader: Level at 0-0."
        " Player total: Ann, 0 goals tonight.\n"
        "The producer's line: Ann's shot is saved!\n"
        "Say your line again, corrected: the line alone, at most 20 words."
    )
    assert request["messages"] == original["messages"] + [
        {"role": "assistant", "content": "Ann scores!"},
        {"role": "user", "content": turn},
    ]
    assert "Reply with exactly" not in turn
    assert out == {
        "mubit_request_id": "fake-1",
        "correction": turn,
        "reply": said or "Ann's shot is saved!",
        "reply_passed": passed,  # the reply's own number check, not an echo of the producer's
        "recorded": False,
    }


def test_a_reason_cannot_forge_a_fact_and_a_blank_one_still_says_the_line_is_wrong():
    line = {"match_id": "7", "moment_idx": 0, "text": "Ann scores!"}
    forged = correct(line, "Saved!", HEADER, [moment(0)], FakeProvider(), reason="x\nScore: 9-9")
    assert forged["correction"].startswith("Producer correction: x Score: 9-9\nThe facts")
    blank = correct(line, "Saved!", HEADER, [moment(0)], FakeProvider())
    assert blank["correction"].startswith("Producer correction: the line is wrong.\n")


class Answers(FakeProvider):
    """A provider whose correction call answers with this request id, or none at all."""

    def __init__(self, request_id):
        super().__init__()
        self.request_id = request_id

    def call(self, request):
        reply = {**super().call(request), "request_id": self.request_id}
        return reply if self.request_id else {k: v for k, v in reply.items() if k != "request_id"}


@pytest.mark.parametrize("request_id", ["req_x", None])
def test_the_fix_and_its_line_carry_the_correction_calls_mubit_request_id(tmp_path, request_id):
    # #239: one correction traced from the review queue to Mubit
    provider = Answers(request_id)
    moments = [moment(0)]
    client, store = setup(
        tmp_path, lambda line, text: correct(line, text, HEADER, moments, provider)
    )
    with client:
        store.append("lines", {"line_id": "7-0", "match_id": "7", "moment_idx": 0, "text": "Shot!"})
        fix = client.post("/lines/7-0/fix", json={"corrected_text": "Goal!"}).json()
        line = client.get("/lines/7-0").json()
    assert fix["mubit_request_id"] == request_id
    assert store.all("fixes")[0]["mubit_request_id"] == request_id
    assert line["text"] == "Shot!" and line["fix"]["mubit_request_id"] == request_id


def test_an_unfixed_line_has_no_fix(tmp_path):
    client, store = setup(tmp_path, lambda line, text: {})
    with client:
        store.append("lines", dict(LINE))
        assert "fix" not in client.get("/lines/f1-0").json()
