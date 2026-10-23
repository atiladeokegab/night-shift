import pytest
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.replay import moment_seconds
from core.smoke import read_stream, replay_match
from core.store import Store, open_store

MOMENTS = {
    "f1": [
        {"sport": "football", "match_id": "f1", "idx": 0, "clock": "03:10", "type": "Shot"},
        {"sport": "football", "match_id": "f1", "idx": 1, "clock": "41:02", "type": "Shot"},
    ],
    "c1": [{"sport": "cricket", "match_id": "c1", "idx": 0, "clock": "19.6", "type": "wicket"}],
}


def fake_commentate(moment, history):
    assert all(h["idx"] < moment["idx"] for h in history)
    return {
        "line_id": f"{moment['match_id']}-{moment['idx']}",
        "text": f"{moment['type']}!",
        "latency_ms": 100 + moment["idx"],
        "first_word_ms": 50,
        "tokens_in": 10,
        "tokens_out": 5,
        "mubit_request_ids": [f"r{moment['match_id']}{moment['idx']}"],
    }


@pytest.fixture
def app_store(tmp_path):
    store = Store(tmp_path)
    deps = Deps(
        list_matches=lambda: [{"match_id": k, "sample": True} for k in MOMENTS],
        load_moments=lambda mid: MOMENTS[mid],
        commentate=fake_commentate,
    )
    with TestClient(create_app(store=store, deps=deps)) as client:
        yield client, store


def test_health(app_store):
    assert app_store[0].get("/health").json() == {"status": "ok"}


def test_replay_streams_in_order_and_stores_every_line(app_store):
    client, store = app_store
    assert replay_match(client, store, "f1") == 2
    assert replay_match(client, store, "c1") == 1
    stats = client.get("/stats").json()
    assert stats["lines"] == 3 and stats["mubit_requests"] == 3 and stats["first_word_ms_p50"] == 50


def test_late_subscriber_gets_the_whole_replay(app_store):
    client, _ = app_store
    rid = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()["replay_id"]
    read_stream(client, rid)
    assert [n for n, _ in read_stream(client, rid)].count("line") == 2


def test_commentator_failure_ends_the_stream_with_error(tmp_path):
    def boom(moment, history):
        raise RuntimeError("provider down")

    deps = Deps(lambda: [], lambda mid: MOMENTS[mid], boom)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()["replay_id"]
        names = [n for n, _ in read_stream(client, rid)]
    assert names == ["moment", "error", "end"]


def test_no_line_leaves_the_moment_silent(tmp_path):
    deps = Deps(lambda: [], lambda mid: MOMENTS[mid], lambda m, h: None)
    store = Store(tmp_path)
    with TestClient(create_app(store=store, deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()["replay_id"]
        names = [n for n, _ in read_stream(client, rid)]
    assert names == ["moment", "moment", "end"] and store.all("lines") == []


def test_unknown_match_and_replay_404(app_store):
    client, _ = app_store
    assert client.post("/replays", json={"match_id": "nope", "speed": 1}).status_code == 404
    assert client.get("/replays/nope/stream").status_code == 404


def test_no_commentator_is_503(tmp_path, monkeypatch):
    monkeypatch.setattr("core.app.default_deps", lambda: None)
    with TestClient(create_app(store=Store(tmp_path))) as client:
        assert client.get("/matches").status_code == 503


def test_cloud_mode_refuses_without_gcs():
    with pytest.raises(RuntimeError, match="STORE_URL"):
        open_store({"MODE": "cloud"})


def test_moment_seconds():
    assert moment_seconds({"sport": "football", "clock": "41:02"}) == 2462
    assert moment_seconds({"sport": "cricket", "clock": "19.6"}) == (19 * 6 + 6) * 30
    assert moment_seconds({"sport": "basketball", "period": 1, "clock": "11:30"}) == 30
    assert moment_seconds({"sport": "basketball", "period": 4, "clock": "00:05"}) == 4 * 720 - 5
    assert moment_seconds({"sport": "basketball", "period": 5, "clock": "04:00"}) == 4 * 720 + 60
