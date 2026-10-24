"""Talk to the commentator (#380): a short-lived signed URL for the browser, and the custom LLM
ElevenLabs calls for each turn, answered by the Ask path and cut at the moment on screen."""

import asyncio
import json
import time
from functools import partial
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent.commentator import FakeProvider, answer
from core import converse, insight
from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import Store
from tests.test_core_ask import HEADER, MOMENTS, line

ENV = {
    "ELEVENLABS_API_KEY": "sk-secret-key",
    "CONVERSE_AGENT_ID": "agent_1",
    "CONVERSE_LLM_SECRET": "llm-secret",
}


def talk(tmp_path, monkeypatch, env=ENV):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    asked = []

    async def signed(agent_id, key):
        asked.append((agent_id, key))
        return "wss://api.elevenlabs.io/convai?conversation_signature=sig"

    provider = FakeProvider()
    ask = partial(answer, header=HEADER, provider=provider)
    deps = Deps(lambda: [], lambda mid: MOMENTS, line, ask=ask)
    monkeypatch.setattr(converse, "signed_url", signed)
    monkeypatch.setattr(converse.commentator, "unrecorded_provider", lambda: provider)
    client = TestClient(create_app(store=Store(tmp_path), deps=deps))
    return client, provider, asked


def started(client):
    rid = client.post("/replays", json={"match_id": "7", "speed": 1e6}).json()["replay_id"]
    read_stream(client, rid)
    return rid


def mint(client, rid, idx=1):
    return client.get(f"/converse/football/7/token?replay_id={rid}&moment_idx={idx}")


def turn(client, ctx, text, secret="llm-secret", **body):
    system = f"You are the commentator. Conversation ctx={ctx}."
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    return client.post(
        "/converse/v1/chat/completions",
        json={"messages": messages, "stream": True, **body},
        headers={"Authorization": f"Bearer {secret}"},
    )


def chunks(resp):
    data = [ln[6:] for ln in resp.text.splitlines() if ln.startswith("data: ")]
    assert data[-1] == "[DONE]"
    return [json.loads(d) for d in data[:-1]]


def test_the_token_route_never_returns_the_api_key(tmp_path, monkeypatch):
    client, _, asked = talk(tmp_path, monkeypatch)
    with client:
        resp = mint(client, started(client))
    assert resp.status_code == 200 and asked == [("agent_1", "sk-secret-key")]
    assert resp.json()["signed_url"].startswith("wss://")
    assert "sk-secret-key" not in resp.text and "llm-secret" not in resp.text


def test_no_key_or_agent_means_no_conversation_so_the_page_asks(tmp_path, monkeypatch):
    client, _, _ = talk(tmp_path, monkeypatch, env={})
    with client:
        assert mint(client, started(client)).status_code == 503


def test_the_token_names_a_real_match_of_that_replay(tmp_path, monkeypatch):
    client, _, _ = talk(tmp_path, monkeypatch)
    with client:
        rid = started(client)
        assert client.get(f"/converse/football/8/token?replay_id={rid}").status_code == 404
        assert client.get(f"/converse/cricket/7/token?replay_id={rid}").status_code == 404
        assert client.get("/converse/football/7/token?replay_id=nope").status_code == 404


def test_a_turn_streams_the_ask_answer_in_the_chat_completions_format(tmp_path, monkeypatch):
    client, provider, _ = talk(tmp_path, monkeypatch)
    with client:
        ctx = mint(client, started(client)).json()["ctx"]
        resp = turn(client, ctx, "What was the final score?")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    got = chunks(resp)
    assert all(c["object"] == "chat.completion.chunk" for c in got)
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in got) == (
        "So far, Reds 1, Blues 0."
    )
    assert got[-1]["choices"][0]["finish_reason"] == "stop"
    assert (
        'Viewer question: "What was the final score?"'
        in provider.requests[-1]["messages"][0]["content"]
    )


def test_the_match_is_cut_at_the_moment_the_conversation_started(tmp_path, monkeypatch):
    client, provider, _ = talk(tmp_path, monkeypatch)
    with client:
        ctx = mint(client, started(client), idx=1).json()["ctx"]
        turn(client, ctx, "Who scored?")
    asked = provider.requests[-1]["messages"][0]["content"]
    assert "Player1" in asked and "Player2" not in asked and "Player3" not in asked


def test_a_follow_up_carries_what_was_just_said(tmp_path, monkeypatch):
    client, provider, _ = talk(tmp_path, monkeypatch)
    with client:
        ctx = mint(client, started(client)).json()["ctx"]
        messages = [
            {"role": "system", "content": f"ctx={ctx}"},
            {"role": "user", "content": "Who scored?"},
            {"role": "assistant", "content": "Player1 scored."},
            {"role": "user", "content": "And how far out?"},
        ]
        auth = {"Authorization": "Bearer llm-secret"}
        client.post("/converse/v1/chat/completions", json={"messages": messages}, headers=auth)
    asked = provider.requests[-1]["messages"][0]["content"]
    assert "And how far out?" in asked and "Player1 scored." in asked


def test_a_turn_needs_the_secret_and_a_context_it_issued(tmp_path, monkeypatch):
    client, provider, _ = talk(tmp_path, monkeypatch)
    with client:
        ctx = mint(client, started(client)).json()["ctx"]
        assert turn(client, ctx, "Who scored?", secret="wrong").status_code == 401
        assert turn(client, "forged" * 6, "Who scored?").status_code == 404
    assert provider.requests == []


def test_off_air_the_agent_says_so_calmly(tmp_path, monkeypatch):
    client, _, _ = talk(tmp_path, monkeypatch)
    with client:
        ctx = mint(client, started(client)).json()["ctx"]
        monkeypatch.setattr(converse.insight, "checked_answer", lambda *a, **k: None)
        resp = turn(client, ctx, "Who scored?", stream=False)
    text = resp.json()["choices"][0]["message"]["content"]
    assert text == "Commentator is off air for a moment"


class SlowClient:
    """The Anthropic SDK's streaming shape: (delay, text) pieces, each after its delay."""

    def __init__(self, pieces):
        self.pieces, self.messages = pieces, self

    def stream(self, **request):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for delay, text in self.pieces:
            time.sleep(delay)
            yield SimpleNamespace(type="text", text=text)

    def get_final_message(self):
        text = "".join(t for _, t in self.pieces)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )


def model(pieces):
    return SimpleNamespace(client=SlowClient(pieces), call=None)


async def sentences(inner, question="Who scored?"):
    ask = partial(answer, header=HEADER)
    past, lines = MOMENTS[:2], []
    return [s async for s in converse.speak(ask, inner, question, past, lines)]


SLOW = [(0.05, "Player1 scored for the Reds. "), (0.6, "A fine finish by Player1.")]


def test_the_first_sentence_is_spoken_before_the_model_has_finished():
    async def run():
        ask, start = partial(answer, header=HEADER), time.monotonic()
        spoken = converse.speak(ask, model(SLOW), "Who scored?", MOMENTS[:2], [])
        first = await anext(spoken)
        at_first = time.monotonic() - start
        rest = [s async for s in spoken]
        return first, at_first, rest

    first, at_first, rest = asyncio.run(run())
    # before: the whole reply was built first, so time-to-speech was the full model call
    ask, start = partial(answer, header=HEADER), time.monotonic()
    tap = converse.Tap(model(SLOW), lambda t: None, lambda: None)
    insight.checked_answer(partial(ask, provider=tap), "Who scored?", MOMENTS[:2], [])
    before = time.monotonic() - start
    assert before > 0.6 and at_first < before / 2
    assert first == "Player1 scored for the Reds."
    assert rest == ["A fine finish by Player1."]


def test_a_sentence_that_fails_the_number_check_stops_the_answer():
    said = asyncio.run(
        sentences(model([(0, "Player1 scored for the Reds. "), (0, "It made it 9-0 to them.")]))
    )
    assert said == ["Player1 scored for the Reds."]


def test_a_first_sentence_that_fails_falls_back_to_the_safe_answer(monkeypatch):
    monkeypatch.setattr(converse.commentator, "unrecorded_provider", FakeProvider)
    inner = model([(0, "The Reds lead 9-0 and Player1 has 40 goals.")])
    said = asyncio.run(sentences(inner))
    assert said and "9-0" not in said[0] and "40" not in said[0]
