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


def test_commentator_error_payload_is_generic(tmp_path):
    def broke(moment, history):
        raise RuntimeError(
            "402 starter_credit_used_up: see https://console.mubit.ai request_id=abc123"
        )

    deps = Deps(lambda: [], lambda mid: MOMENTS[mid], broke)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()["replay_id"]
        error = dict(read_stream(client, rid))["error"]
    assert error == {"code": "commentator_off_air", "detail": "Commentator is off air for a moment"}


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
    assert moment_seconds({"sport": "f1", "period": 52, "clock": "82:26"}) == 82 * 60 + 26


def test_a_failed_model_call_is_logged_with_its_error(tmp_path, caplog):
    def broke(moment, history):  # Mubit's reply when the credit ran out (sweep 5)
        raise RuntimeError("Error code: 402 - {'error': {'type': 'starter_credit_used_up'}}")

    deps = Deps(lambda: [], lambda mid: MOMENTS[mid], broke)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": "f1", "speed": 1e6}).json()["replay_id"]
        read_stream(client, rid)
    assert "replay f1 stopped: RuntimeError: Error code: 402" in caplog.text
    assert "starter_credit_used_up" in caplog.text


async def sse(app, rid: str, leave_after: int | None = None) -> bytes:
    """GET the replay's stream as a browser would, closing it after `leave_after` lines (else
    reading to the end): TestClient cannot disconnect mid-stream."""
    import asyncio

    body, asked = b"", False

    async def receive():
        nonlocal asked
        if not asked:
            asked = True
            return {"type": "http.request", "body": b"", "more_body": False}
        while leave_after is None or body.count(b"event: line") < leave_after:
            await asyncio.sleep(0.01)
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal body
        body += message.get("body", b"")

    path = f"/replays/{rid}/stream"
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": [], "server": ("t", 80), "client": ("t", 1)}  # fmt: skip
    await app(scope, receive, send)
    return body


LONG = [  # a match long enough to be walked away from
    {"sport": "football", "match_id": "long", "idx": i, "clock": f"{i:02d}:00", "type": "Shot"}
    for i in range(60)
]


def abandoned_replay(tmp_path, monkeypatch, follow: bool):
    """Start a long replay whose voice jobs all hang, optionally follow it until 4 lines, leave,
    then let the voice calls through: the model calls and voice calls made, before and after."""
    import asyncio
    import json
    import time

    import httpx

    from core import app as core_app

    monkeypatch.setattr(core_app, "REJOIN_S", 0.2)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    said, voiced = [], []

    def commentate(moment, history):
        said.append(moment["idx"])
        time.sleep(0.01)
        return {**fake_commentate(moment, history), "line_id": f"long-{moment['idx']}"}

    async def run():
        gate = asyncio.Event()

        async def tts(request: httpx.Request) -> httpx.Response:
            voiced.append(json.loads(request.content)["model_id"])
            await gate.wait()
            return httpx.Response(200, content=b"ID3")

        deps = Deps(lambda: [], lambda mid: LONG, commentate)
        app = create_app(Store(tmp_path), deps, tts_transport=httpx.MockTransport(tts))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/replays", json={"match_id": "long", "speed": 600.0})
        rid = r.json()["replay_id"]
        if follow:
            await sse(app, rid, leave_after=4)
        await asyncio.sleep(0.5)  # past REJOIN_S
        before = (len(said), len(voiced))
        gate.set()  # anything still queued would now reach ElevenLabs
        await asyncio.sleep(0.5)
        return before, (len(said), len(voiced))

    return asyncio.run(run())


def test_a_replay_whose_stream_closed_stops_calling_the_model_and_frees_its_voice_slots(
    tmp_path, monkeypatch
):
    (said, voiced), after = abandoned_replay(tmp_path, monkeypatch, follow=True)
    assert 4 <= said < len(LONG)  # stopped: at 600x the whole match takes ~6 s
    assert voiced == 3  # the 3 shared slots were busy; the queued lines never went out
    assert after == (said, voiced)


def test_a_replay_nobody_follows_is_stopped_too(tmp_path, monkeypatch):
    (said, voiced), after = abandoned_replay(tmp_path, monkeypatch, follow=False)
    assert said < len(LONG) and after == (said, voiced)


def test_a_stream_that_reconnects_in_time_keeps_its_replay(tmp_path, monkeypatch):
    # an EventSource reconnects by itself after a dropped connection (/stage, the main page)
    import asyncio

    import httpx

    from core import app as core_app

    monkeypatch.setattr(core_app, "REJOIN_S", 0.3)
    short = LONG[:12]
    deps = Deps(lambda: [], lambda mid: short, fake_commentate)
    app = create_app(Store(tmp_path), deps)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/replays", json={"match_id": "long", "speed": 600.0})
        rid = r.json()["replay_id"]
        await sse(app, rid, leave_after=2)
        await asyncio.sleep(0.1)  # back within REJOIN_S
        return await sse(app, rid)

    body = asyncio.run(run())
    assert body.count(b"event: line") == len(short) and b"event: end" in body
