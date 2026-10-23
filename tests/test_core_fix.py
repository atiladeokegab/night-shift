"""The fix loop (R-4): POST /lines/{id}/fix stores the fix beside the line, sends it as the next
turn of the line's own Mubit call, records reply_matched and marks the line fixed on the stream."""

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

    def fake_correct(line, text):
        sent.append((line["line_id"], text))
        return {"mubit_request_id": "r-fix", "reply_matched": True}

    client, store = setup(tmp_path, fake_correct)
    with client:
        replay_id = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()
        read_stream(client, replay_id["replay_id"])  # the replay has finished
        resp = client.post("/lines/f1-0/fix", json={"corrected_text": " Goal! ", "reason": "wrong"})
        events = read_stream(client, replay_id["replay_id"])
        stats = client.get("/stats").json()
    fix = resp.json()
    assert resp.status_code == 200
    assert sent == [("f1-0", "Goal!")]
    assert {k: fix[k] for k in ("line_id", "corrected_text", "reason")} == {
        "line_id": "f1-0",
        "corrected_text": "Goal!",
        "reason": "wrong",
    }
    assert fix["mubit_request_id"] == "r-fix" and fix["reply_matched"] is True and fix["created_at"]
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


@pytest.mark.parametrize(("said", "matched"), [(None, True), ("Something else.", False)])
def test_correction_is_the_next_turn_of_the_same_task_and_session(said, matched):
    moments = [moment(0), moment(1), moment(2)]
    provider = FakeProvider() if said is None else Says(said)
    line = {"match_id": "7", "moment_idx": 1, "text": "Saved by the keeper!"}
    out = correct(line, "Ann's shot is saved!", HEADER, moments, provider)
    original = build_request(HEADER, moments[:2])  # a later moment never reaches the model
    request = provider.requests[-1]
    assert {k: v for k, v in request.items() if k != "messages"} == {
        k: v for k, v in original.items() if k != "messages"
    }
    assert request["messages"] == original["messages"] + [
        {"role": "assistant", "content": "Saved by the keeper!"},
        {
            "role": "user",
            "content": "Producer correction. Reply with exactly this line: Ann's shot is saved!",
        },
    ]
    assert out == {"mubit_request_id": "fake-1", "reply_matched": matched}
