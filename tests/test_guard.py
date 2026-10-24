"""The budget guard (#244): replays generating new lines at once, replay starts and Asks per client
an hour, and the daily spend cap, each with the clock injected."""

import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.guard import Guard, Limiter, spent
from core.smoke import read_stream
from core.store import Store

NOON = datetime(2026, 10, 24, 12, tzinfo=UTC).timestamp()


def moment(idx):
    return {
        "sport": "football",
        "match_id": "7",
        "idx": idx,
        "period": 1,
        "clock": f"{idx:02d}:00",
        "type": "Shot",
        "team": "Reds",
        "players": {},
        "outcome": "Saved",
        "score": {"home": 0, "away": 0},
        "detail": {},
    }


MOMENTS = [moment(0), moment(1), moment(2)]


def stored(store, day="2026-10-24", **cost):
    """A line already said for each moment of match 7."""
    for m in MOMENTS:
        store.append(
            "lines",
            {
                "line_id": f"old{m['idx']}",
                "match_id": "7",
                "moment_idx": m["idx"],
                "speaker": "lead",
                "text": f"Stored {m['idx']}",
                "created_at": f"{day}T09:00:00+00:00",
                **cost,
            },
        )


def app(store, env, commentate=None, ask=None, clock=lambda: NOON):
    calls = []

    def said(m, history):
        calls.append(m["idx"])
        return {"line_id": f"new{m['idx']}", "match_id": "7", "moment_idx": m["idx"], "text": "New"}

    deps = Deps(lambda: [], lambda mid: MOMENTS, commentate or said, ask=ask)
    guard = Guard(env, clock)
    return TestClient(create_app(store=store, deps=deps, guard=guard)), calls


def start(client, match_id="7", ip="1.1.1.1"):
    return client.post(
        "/replays", json={"match_id": match_id, "speed": 1e6}, headers={"x-forwarded-for": ip}
    )


def texts(client, replay_id):
    return [d["text"] for n, d in read_stream(client, replay_id) if n == "line"]


def test_a_client_gets_its_hourly_starts_then_429_with_retry_after(tmp_path):
    client, _ = app(Store(tmp_path), {"REPLAYS_PER_HOUR": "2"})
    with client:
        ok = [start(client, ip="1.1.1.1, 10.0.0.1").status_code for _ in range(2)]
        over = start(client, ip="1.1.1.1, 10.0.0.2")  # the first hop is the client
        other = start(client, ip="2.2.2.2")
    assert ok == [200, 200]
    assert over.status_code == 429 and 0 < int(over.headers["retry-after"]) <= 3600
    assert "Try again" in over.json()["detail"]
    assert other.status_code == 200


def test_the_limiter_forgets_hits_older_than_an_hour():
    now = [0.0]
    limit = Limiter(2, lambda: now[0])
    assert [limit.hit("a"), limit.hit("a")] == [0, 0]
    now[0] = 1800.0
    assert limit.hit("a") == 1800  # the first hit leaves the hour at 3600
    now[0] = 3600.0
    assert limit.hit("a") == 0
    assert Limiter(0).hit("a") == 0  # 0: off


def test_asks_over_the_hourly_limit_get_429(tmp_path):
    asked = []

    def ask(question, past, lines):
        asked.append(question)
        return {"line_id": "a", "moment_idx": past[-1]["idx"], "question": question, "text": "Yes"}

    client, _ = app(Store(tmp_path), {"ASKS_PER_HOUR": "1"}, ask=ask)
    with client:
        rid = start(client).json()["replay_id"]
        read_stream(client, rid)
        first = client.post(f"/replays/{rid}/ask", json={"question": "Who?"})
        second = client.post(f"/replays/{rid}/ask", json={"question": "Why?"})
    assert first.status_code == 200 and asked == ["Who?"]
    assert second.status_code == 429 and second.headers["retry-after"]


def test_beyond_max_live_a_replay_plays_stored_lines_or_429(tmp_path):
    store, gate, calls = Store(tmp_path), threading.Event(), []
    stored(store)

    def slow(m, history):  # the first replay holds its live slot until the gate opens
        calls.append(m["idx"])
        gate.wait(5)
        return {"line_id": f"new{m['idx']}", "match_id": "7", "moment_idx": m["idx"], "text": "New"}

    client, _ = app(store, {"MAX_LIVE_REPLAYS": "1"}, commentate=slow)
    with client:
        first = start(client).json()["replay_id"]
        second = start(client).json()["replay_id"]
        cached = texts(client, second)
        unknown = start(client, match_id="8")  # nothing stored for it
        gate.set()
        read_stream(client, first)
    assert cached == ["Stored 0", "Stored 1", "Stored 2"]
    assert calls == [0, 1, 2]  # only the first replay called the model
    assert unknown.status_code == 429 and unknown.headers["retry-after"] == "60"


def test_over_the_daily_cap_lines_replay_from_the_store_and_ask_is_off_air(tmp_path):
    store = Store(tmp_path)
    stored(store, model="claude-haiku-4-5", tokens_in=1_000_000)  # $1 a line, $3 today
    asked = []
    client, calls = app(store, {"DAILY_BUDGET_USD": "2"}, ask=lambda *a: asked.append(a))
    with client:
        budget = client.get("/stats").json()["budget"]
        rid = start(client).json()["replay_id"]
        lines = texts(client, rid)
        answer = client.post(f"/replays/{rid}/ask", json={"question": "Who?"}).json()
        audio = client.get("/lines/old0/audio")
        unknown = start(client, match_id="8")
    assert budget == {"daily_budget_usd": 2.0, "spent_today_usd": 3.0, "off_air": True}
    assert lines == ["Stored 0", "Stored 1", "Stored 2"] and calls == []
    assert answer["text"] == answer["notice"] == "Commentator is off air for today"
    assert answer["off_air"]
    assert asked == []
    assert audio.status_code == 503 and audio.json()["detail"] == "voice off air for today"
    assert unknown.status_code == 429
    assert int(unknown.headers["retry-after"]) == 12 * 3600  # noon to midnight UTC
    # the replayed lines are stored again at no cost: today's spend is unchanged
    assert spent(store, "2026-10-24") == 3.0


def test_spend_counts_only_today_with_its_voice(tmp_path):
    store = Store(tmp_path)
    stored(store, day="2026-10-23", model="claude-haiku-4-5", tokens_in=1_000_000)
    store.append("answers", {"line_id": "a1", "created_at": "2026-10-24T08:00:00+00:00"})
    store.append("voice", {"line_id": "a1", "model": "eleven_v3", "chars": 1000})
    store.append("voice", {"line_id": "old0", "model": "eleven_v3", "chars": 1000})
    assert spent(store, "2026-10-24") == pytest.approx(0.08)
    assert spent(store, "2026-10-23") == pytest.approx(3.08)
    assert not Guard({"DAILY_BUDGET_USD": "0"}).off_air(store)  # 0: off
