"""Score check asked live on each fresh line, so a version the console serves answers it: never on
cached playback or the smoke, held-out matches unrecorded, "wrong" queued, failures dropped."""

import json

from fastapi.testclient import TestClient

from agent import scorecheck
from core.app import Deps, create_app
from core.replay import live_score_check
from core.review import SCORE_WRONG
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments, match_header
from eval.linecheck import gold

KOBE = "0020500591"  # idx 6: Bryant's three for 47 points, Lakers 73, Raptors 78
RIGHT = "Kobe Bryant from deep! He's got 47 points, Lakers trail 73 to 78!"
WSL = "3913122"  # held out: never recorded


class Says:
    """A fake Mubit that answers every call with `label`, keeping each request."""

    def __init__(self, label="ok"):
        self.label, self.requests = label, []

    def call(self, req):
        self.requests.append(json.loads(json.dumps(req)))
        if isinstance(self.label, Exception):
            raise self.label
        return {
            "content": [{"type": "text", "text": scorecheck.dumps(self.label)}],
            "usage": {"input_tokens": 200, "output_tokens": 10},
            "request_id": f"sc-{len(self.requests)}",
            "served_by": "score-check-v2",
        }


def _providers(monkeypatch, recorded, unrecorded=None):
    monkeypatch.setattr("agent.commentator.default_provider", lambda: recorded)
    monkeypatch.setattr("agent.commentator.unrecorded_provider", lambda: unrecorded or Says())


def _at(match_id, idx):
    moments = load_moments(match_id)
    i = next(i for i, m in enumerate(moments) if m["idx"] == idx)
    return moments[i], moments[:i]


def test_the_live_call_is_the_seeded_request_with_code_answer(monkeypatch):
    fake = Says("ok")
    _providers(monkeypatch, fake)
    m, past = _at(KOBE, 6)
    line = {"line_id": "k6", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}
    got = live_score_check(line, m, past)
    assert fake.requests == [scorecheck.build_request(match_header(KOBE), m, RIGHT)]
    assert got["label"] == "ok" and got["code"] == gold(match_header(KOBE), m, past, RIGHT)["score"]
    assert (got["served_by"], got["mubit_request_id"]) == ("score-check-v2", "sc-1")


def test_a_held_out_match_uses_the_unrecorded_provider(monkeypatch):
    recorded, unrecorded = Says(), Says()
    _providers(monkeypatch, recorded, unrecorded)
    m, past = _at(WSL, load_moments(WSL)[3]["idx"])
    line = {"line_id": "w", "match_id": WSL, "moment_idx": m["idx"], "text": "Still goalless!"}
    assert live_score_check(line, m, past)["label"] == "ok"
    assert (len(recorded.requests), len(unrecorded.requests)) == (0, 1)


def _line_check(line, m, past):  # Line check's call was made: Score check follows it
    return {"labels": None, "wrong": []}


def _app(tmp_path, check=_line_check):
    def commentate(m, history):  # moment 6's line only; the rest say nothing
        if m["idx"] == 6:
            return {"line_id": "k6", "match_id": KOBE, "moment_idx": 6, "text": RIGHT}

    store = Store(tmp_path)
    deps = Deps(list_matches, load_moments, commentate, linecheck=check)
    return TestClient(create_app(store=store, deps=deps)), store


def _play(client, **kw):
    rid = client.post("/replays", json={"match_id": KOBE, "speed": 1e9, "start_idx": 6, **kw})
    return read_stream(client, rid.json()["replay_id"])


def test_a_fresh_line_is_asked_and_wrong_is_queued_and_counted(tmp_path, monkeypatch):
    fake = Says("wrong")
    _providers(monkeypatch, fake)
    client, store = _app(tmp_path)
    with client:
        events = _play(client)
        for m in load_moments(KOBE)[7:]:  # every moment said, so the next replay plays them back
            store.append(
                "lines",
                {
                    "line_id": f"s{m['idx']}",
                    "match_id": KOBE,
                    "moment_idx": m["idx"],
                    "text": "Shot!",
                },
            )
        cached = _play(client)  # the stored lines played again: no call
        _play(client, smoke=True)  # the deploy's smoke: no second opinion
        queued = client.get("/review").json()
        stats = client.get("/stats").json()
    assert any(n == "line" for n, _ in events) and len(fake.requests) == 1
    assert any(n == "line" for n, _ in cached)
    entry = next(q for q in queued if q["line_id"] == "k6")
    assert SCORE_WRONG in entry["wrong"]
    assert stats["scorecheck_live"] == {
        "calls": 1,
        "agreed": 0,  # code says the line's score is right
        "by_served_by": {"score-check-v2": 1},
    }


def test_a_failed_call_is_dropped_and_the_line_airs(tmp_path, monkeypatch):
    _providers(monkeypatch, Says(ConnectionError("mubit down")))
    client, store = _app(tmp_path)
    with client:
        events = _play(client)
    assert any(n == "line" for n, _ in events) and "error" not in [n for n, _ in events]
    assert store.all("scorechecks") == []


def test_no_line_check_call_no_score_check(tmp_path, monkeypatch):
    fake = Says("ok")
    _providers(monkeypatch, fake)
    client, store = _app(tmp_path, lambda *a: None)  # over the cap, or offline
    with client:
        _play(client)
    assert fake.requests == [] and store.all("scorechecks") == []


def test_a_non_canonical_reply_is_stored_with_its_tokens(tmp_path, monkeypatch):
    class Rambles(Says):
        def call(self, req):
            reply = super().call(req)
            return {**reply, "content": [{"type": "text", "text": "The score looks fine."}]}

    _providers(monkeypatch, Rambles())
    client, store = _app(tmp_path)
    with client:
        _play(client)
        queued = client.get("/review").json()
        live = client.get("/stats").json()["scorecheck_live"]
    (row,) = store.all("scorechecks")
    assert row["label"] is None and (row["tokens_in"], row["tokens_out"]) == (200, 10)
    assert not any(SCORE_WRONG in q["wrong"] for q in queued)
    assert (live["calls"], live["agreed"]) == (1, 0)
