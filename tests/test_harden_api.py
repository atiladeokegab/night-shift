"""The API boundary: /health tells the truth, and a producer-only flag needs the producer token."""

from fastapi.testclient import TestClient

from core import app as core_app
from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import Store
from data.matches import load_moments


def test_health_is_not_ok_when_the_commentator_failed_to_import(tmp_path, monkeypatch):
    # every replay route says 503 then: /health (the deploy's check) must not say "ok"
    monkeypatch.setattr(core_app, "default_deps", lambda: None)
    with TestClient(create_app(store=Store(tmp_path))) as client:
        assert client.get("/matches").status_code == 503
        resp = client.get("/health")
    assert resp.status_code == 503 and resp.json().get("status") != "ok"


def smoke_replay(tmp_path, monkeypatch, headers):
    monkeypatch.setenv("PRODUCER_TOKEN", "secret")
    checked = []
    deps = Deps(
        list_matches=lambda: [{"match_id": "9636", "sample": True}],
        load_moments=load_moments,  # a bundled match: only its lines pass the number check
        commentate=lambda m, h: {"line_id": f"l{m['idx']}", "text": "What a moment!"},
        linecheck=lambda line, m, h: checked.append(line["line_id"]),
    )
    store = Store(tmp_path)
    with TestClient(create_app(store=store, deps=deps)) as client:
        body = {"match_id": "9636", "speed": 1e6, "smoke": True}
        read_stream(client, client.post("/replays", json=body, headers=headers).json()["replay_id"])
    return checked, store.all("replays")


def test_a_smoke_flag_without_the_producer_token_keeps_the_line_check_and_counts(
    tmp_path, monkeypatch
):
    # a viewer's bare `smoke` must not switch off the second opinion on lines it pays for
    checked, replays = smoke_replay(tmp_path, monkeypatch, {})
    assert checked and len(replays) == 1


def test_the_producers_smoke_still_skips_the_line_check(tmp_path, monkeypatch):
    checked, replays = smoke_replay(tmp_path, monkeypatch, {"x-producer-token": "secret"})
    assert checked == [] and replays == []
