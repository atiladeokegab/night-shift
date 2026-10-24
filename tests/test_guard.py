"""The budget guard (#244): replays generating new lines at once, replay starts and Asks per client
an hour, and the daily spend cap, each with the clock injected."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.guard import Guard, Limiter, spent
from core.smoke import read_stream
from core.stats import stats
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


def app(store, env, commentate=None, ask=None, clock=lambda: NOON, tts=None):
    calls = []

    def said(m, history):
        calls.append(m["idx"])
        return {"line_id": f"new{m['idx']}", "match_id": "7", "moment_idx": m["idx"], "text": "New"}

    deps = Deps(lambda: [], lambda mid: MOMENTS, commentate or said, ask=ask)
    guard = Guard(env, clock)
    return TestClient(create_app(store=store, deps=deps, tts_transport=tts, guard=guard)), calls


def start(client, match_id="7", ip="1.1.1.1"):
    return client.post(
        "/replays", json={"match_id": match_id, "speed": 1e6}, headers={"x-forwarded-for": ip}
    )


def texts(client, replay_id):
    return [d["text"] for n, d in read_stream(client, replay_id) if n == "line"]


def test_a_cache_only_replay_publishes_stored_lines_and_stores_nothing(tmp_path):
    store = Store(tmp_path)
    stored(store, model="claude-haiku-4-5", tokens_in=1000)
    store.append(
        "fixes", {"line_id": "old1", "corrected_text": "Fixed, well saved", "recorded": True}
    )
    before = stats(store)
    client, calls = app(store, {"DAILY_BUDGET_USD": "0.001"})  # $0.003 today: past the cap
    with client:
        events = read_stream(client, start(client).json()["replay_id"])
    said = [(d["line_id"], d["text"]) for n, d in events if n == "line"]
    assert said[0] == ("old0", "Stored 0") and said[2] == ("old2", "Stored 2") and calls == []
    assert (
        said[1][1] == "Fixed, well saved"
    )  # the producer's fix is heard (#232), read from `fixes`
    assert len(store.all("lines")) == 3 and store.all("replays") == []
    assert len(store.all("fixes")) == 1
    assert stats(store) == before  # the Proof card does not move


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


def test_beyond_max_live_a_replay_plays_stored_lines_or_429(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    voiced = []
    tts = httpx.MockTransport(lambda req: voiced.append(req) or httpx.Response(200, content=b"mp3"))
    store, gate, calls = Store(tmp_path), threading.Event(), []
    stored(store)

    def slow(m, history):  # the first replay holds its live slot until the gate opens
        calls.append(m["idx"])
        gate.wait(5)
        return {"line_id": f"new{m['idx']}", "match_id": "7", "moment_idx": m["idx"], "text": "New"}

    client, _ = app(store, {"MAX_LIVE_REPLAYS": "1"}, commentate=slow, tts=tts)
    with client:
        assert client.get("/lines/old0/audio").status_code == 200 and len(voiced) == 1
        first = start(client).json()["replay_id"]
        second = start(client).json()["replay_id"]
        cached = texts(client, second)
        audio = [client.get(f"/lines/old{i}/audio") for i in range(3)]
        # old0's saved audio plays again; the others get browser speech: no new ElevenLabs call
        assert [a.status_code for a in audio] == [200, 503, 503] and audio[0].content == b"mp3"
        assert len(voiced) == 1
        unknown = start(client, match_id="8")  # nothing stored for it
        gate.set()
        read_stream(client, first)
    assert len(store.all("lines")) == 6  # the stored three, and the first replay's three
    assert cached == ["Stored 0", "Stored 1", "Stored 2"]
    assert calls == [0, 1, 2]  # only the first replay called the model
    assert unknown.status_code == 429 and unknown.headers["retry-after"] == "60"


def test_over_the_daily_cap_lines_replay_from_the_store_and_ask_is_off_air(tmp_path):
    store = Store(tmp_path)
    stored(store, model="claude-haiku-4-5", tokens_in=1_000_000)  # $1 a line, $3 today
    store.append("lines", {"line_id": "other", "match_id": "9", "moment_idx": 0, "text": "Hi"})
    asked = []
    client, calls = app(store, {"DAILY_BUDGET_USD": "2"}, ask=lambda *a: asked.append(a))
    with client:
        budget = client.get("/stats").json()["budget"]
        rid = start(client).json()["replay_id"]
        lines = texts(client, rid)
        answer = client.post(f"/replays/{rid}/ask", json={"question": "Who?"}).json()
        audio = client.get("/lines/other/audio")  # in no cached replay: the cap stops its voice
        unknown = start(client, match_id="8")
    assert budget == {"daily_budget_usd": 2.0, "spent_today_usd": 3.0, "off_air": True}
    assert lines == ["Stored 0", "Stored 1", "Stored 2"] and calls == []
    assert answer["text"] == answer["notice"] == "Commentator is off air for today"
    assert answer["off_air"]
    assert asked == []
    assert audio.status_code == 503 and audio.json()["detail"] == "voice off air for today"
    assert unknown.status_code == 429
    assert int(unknown.headers["retry-after"]) == 12 * 3600  # noon to midnight UTC
    assert len(store.all("lines")) == 4 and spent(store, "2026-10-24") == 3.0


def test_spend_counts_only_today_with_its_voice(tmp_path):
    store = Store(tmp_path)
    stored(store, day="2026-10-23", model="claude-haiku-4-5", tokens_in=1_000_000)
    store.append("answers", {"line_id": "a1", "created_at": "2026-10-24T08:00:00+00:00"})
    store.append("voice", {"line_id": "a1", "model": "eleven_v3", "chars": 1000})
    store.append("voice", {"line_id": "old0", "model": "eleven_v3", "chars": 1000})
    assert spent(store, "2026-10-24") == pytest.approx(0.08)
    assert spent(store, "2026-10-23") == pytest.approx(3.08)
    assert not Guard({"DAILY_BUDGET_USD": "0"}).off_air(store)  # 0: off


def test_a_store_read_error_keeps_the_site_on_air_and_retries(tmp_path):
    class Broken(Store):
        down = True

        def all(self, kind):
            if self.down and kind == "voice":
                raise OSError("bucket unreachable")
            return super().all(kind)

    store = Broken(tmp_path)
    stored(store, model="claude-haiku-4-5", tokens_in=1_000_000)  # $3 today
    assert not Guard({"DAILY_BUDGET_USD": "2"}).off_air(store)  # unread: 0 spent, on air
    client, _ = app(store, {"DAILY_BUDGET_USD": "2"})
    with client:
        assert start(client).status_code == 200
        store.down = False
        assert client.get("/stats").json()["budget"]["off_air"]  # read again at once: not stamped


def test_two_asks_at_once_get_one_answer_and_one_409(tmp_path, monkeypatch):
    both, racing = threading.Barrier(2, timeout=5), []

    def off_air(self, store):
        if racing:  # both asks read the cap before either claims the slot
            both.wait()
        return False

    def ask(question, past, lines):
        time.sleep(0.2)
        return {
            "line_id": question,
            "moment_idx": past[-1]["idx"],
            "question": question,
            "text": "Yes",
        }

    monkeypatch.setattr(Guard, "off_air", off_air)
    client, _ = app(Store(tmp_path), {}, ask=ask)
    with client:
        rid = start(client).json()["replay_id"]
        read_stream(client, rid)
        racing.append(True)

        def post(q):
            return client.post(f"/replays/{rid}/ask", json={"question": q}).status_code

        with ThreadPoolExecutor(2) as pool:
            codes = sorted(pool.map(post, ["Who?", "Why?"]))
    assert codes == [200, 409]
