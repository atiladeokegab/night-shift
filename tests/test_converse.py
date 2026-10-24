"""Talk to the commentator (#380): a short-lived signed URL for the browser, and the custom LLM
ElevenLabs calls for each turn, answered by the Ask path and cut at the moment on screen."""

import json
from functools import partial

from fastapi.testclient import TestClient

from agent.commentator import FakeProvider, answer
from core import converse
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
