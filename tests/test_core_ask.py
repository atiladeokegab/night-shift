"""Ask the commentator (#117): POST /replays/{id}/ask answers a viewer's question from the match so
far, stores it, publishes it on the stream and speaks it; off air it gives the calm copy."""

import asyncio
import threading
from functools import partial

import httpx
from fastapi.testclient import TestClient

from agent.commentator import FakeProvider, answer
from core.app import Deps, asked_so_far, create_app
from core.replay import OFF_AIR, Replay
from core.smoke import read_stream
from core.store import Store

HEADER = {
    "sport": "football",
    "match_id": "7",
    "home": "Reds",
    "away": "Blues",
    "competition": "Cup",
    "stage": "Final",
    "date": "2020-01-01",
}


def moment(idx, home):
    return {
        "sport": "football",
        "match_id": "7",
        "idx": idx,
        "period": 1,
        "clock": f"{idx:02d}:00",
        "type": "Shot",
        "team": "Reds",
        "players": {"shooter": f"Player{idx}"},
        "outcome": "Goal" if idx else "Saved",
        "score": {"home": home, "away": 0},
        "detail": {},
    }


# Reds score at 1, 2 and 3: 3-0 at full time
MOMENTS = [moment(0, 0), moment(1, 1), moment(2, 2), moment(3, 3)]


def line(m, history):
    return {"line_id": f"l{m['idx']}", "match_id": "7", "moment_idx": m["idx"], "text": "Goal!"}


def setup(tmp_path, ask):
    store = Store(tmp_path)
    deps = Deps(lambda: [], lambda mid: MOMENTS, line, ask=ask)
    return TestClient(create_app(store=store, deps=deps)), store


def finished_replay(client):
    replay_id = client.post("/replays", json={"match_id": "7", "speed": 1e6}).json()["replay_id"]
    read_stream(client, replay_id)
    return replay_id


def test_a_final_score_question_mid_match_gets_the_score_so_far(tmp_path):
    provider = FakeProvider()
    client, store = setup(tmp_path, partial(answer, header=HEADER, provider=provider))
    with client:
        rid = finished_replay(client)
        q = {"question": "What was the final score?", "moment_idx": 1}
        resp = client.post(f"/replays/{rid}/ask", json=q)
        events = read_stream(client, rid)
        audio = client.get(f"/lines/{resp.json()['line_id']}/audio")
    said = resp.json()
    assert resp.status_code == 200 and said["text"] == "So far, Reds 1, Blues 0."
    assert said["question"] == "What was the final score?" and said["moment_idx"] == 1
    request = provider.requests[-1]["messages"][0]["content"]
    assert "Player1" in request and "Player2" not in request and "Player3" not in request
    assert "Viewer question: What was the final score?" in request
    assert store.all("answers") == [said] and said["replay_id"] == rid
    assert ("answer", said) in events
    assert audio.status_code == 503  # found and spoken like a line; this test has no voice key


def test_the_window_never_runs_past_what_the_replay_has_sent():
    replay = Replay("7", 1.0)
    replay.events = [
        *({"event": "moment", "data": m} for m in MOMENTS[:2]),
        *({"event": "line", "data": line(m, [])} for m in MOMENTS[:2]),
    ]
    for on_screen in (None, 1, 99):  # the page cannot ask from a moment not yet sent
        past, lines = asked_so_far(replay, MOMENTS, on_screen)
        assert [m["idx"] for m in past] == [0, 1] and [ln["moment_idx"] for ln in lines] == [0, 1]
    past, lines = asked_so_far(replay, MOMENTS, 0)  # the video is behind the stream
    assert [m["idx"] for m in past] == [0] and [ln["moment_idx"] for ln in lines] == [0]
    assert asked_so_far(Replay("7", 1.0), MOMENTS, None) == ([], [])


def test_off_air_is_the_calm_copy_and_stores_nothing(tmp_path):
    def broke(question, past, lines):
        raise RuntimeError("402 Payment Required: credit used up, see https://console.mubit.ai")

    client, store = setup(tmp_path, broke)
    with client:
        rid = finished_replay(client)
        resp = client.post(f"/replays/{rid}/ask", json={"question": "Who scored?"})
        events = read_stream(client, rid)
    said = resp.json()
    assert resp.status_code == 200
    assert said["off_air"] is True and said["text"] == OFF_AIR and said["moment_idx"] == 3
    assert "402" not in resp.text and "mubit" not in resp.text
    assert store.all("answers") == [] and ("answer", said) in events


def test_bad_questions_and_unknown_replays(tmp_path):
    client, _ = setup(tmp_path, lambda q, p, ln: {})
    with client:
        rid = finished_replay(client)
        assert client.post(f"/replays/{rid}/ask", json={"question": "  "}).status_code == 422
        too_long = {"question": "x" * 201}
        assert client.post(f"/replays/{rid}/ask", json=too_long).status_code == 422
        assert client.post("/replays/nope/ask", json={"question": "Who?"}).status_code == 404


def test_one_question_in_flight_per_replay(tmp_path):
    release = threading.Event()

    def slow(question, past, lines):
        release.wait(5)
        return {"line_id": "a1", "moment_idx": past[-1]["idx"], "text": "Three nil."}

    deps = Deps(lambda: [], lambda mid: MOMENTS, line, ask=slow)
    app = create_app(Store(tmp_path), deps)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            rid = (await c.post("/replays", json={"match_id": "7", "speed": 1e6})).json()
            rid = rid["replay_id"]
            await asyncio.sleep(0.2)  # the replay has sent its moments
            first = asyncio.create_task(c.post(f"/replays/{rid}/ask", json={"question": "Score?"}))
            await asyncio.sleep(0.2)
            second = await c.post(f"/replays/{rid}/ask", json={"question": "And now?"})
            release.set()
            return (await first).status_code, second.status_code

    assert asyncio.run(run()) == (200, 409)
