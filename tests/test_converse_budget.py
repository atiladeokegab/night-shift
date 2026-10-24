"""Talk turns share the fan's Ask limit and count toward the daily model budget."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import commentator
from agent.commentator import FakeProvider, answer
from core import converse
from core.app import Deps, create_app
from core.guard import Guard
from core.smoke import read_stream
from core.store import Store
from tests.test_core_ask import HEADER, MOMENTS, line

ENV = {
    "ELEVENLABS_API_KEY": "dummy-elevenlabs-key",
    "CONVERSE_AGENT_ID": "agent_test",
    "CONVERSE_LLM_SECRET": "dummy-llm-secret",
}


def app_for(tmp_path, monkeypatch, *, asks_per_hour=20, daily_budget=50.0, usage=True):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    async def signed_url(*_):
        return "wss://example.test/conversation"

    monkeypatch.setattr(converse, "signed_url", signed_url)
    provider = FakeProvider()
    monkeypatch.setattr(commentator, "unrecorded_provider", lambda: provider)

    def ask(question, past, lines, provider=None, **kwargs):
        result = answer(
            question,
            past,
            lines,
            header=HEADER,
            provider=provider or commentator.unrecorded_provider(),
            **kwargs,
        )
        if not usage:
            result.pop("tokens_in")
        return result

    store = Store(tmp_path)
    guard = Guard(
        env={
            "ASKS_PER_HOUR": str(asks_per_hour),
            "DAILY_BUDGET_USD": str(daily_budget),
        }
    )
    deps = Deps(lambda: [], lambda _match_id: MOMENTS, line, ask=ask)
    client = TestClient(create_app(store=store, deps=deps, guard=guard))
    return client, provider, store, guard


def start_replay(client):
    replay_id = client.post("/replays", json={"match_id": "7", "speed": 1e6}).json()["replay_id"]
    read_stream(client, replay_id)
    return replay_id


def mint(client, replay_id, ip="198.51.100.7"):
    return client.get(
        f"/converse/football/7/token?replay_id={replay_id}&moment_idx=1",
        headers={"x-forwarded-for": ip},
    ).json()["ctx"]


def turn(client, ctx, ip="203.0.113.9"):
    return client.post(
        "/converse/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": f"You are the commentator. ctx={ctx}"},
                {"role": "user", "content": "Who scored?"},
            ],
            "stream": True,
        },
        headers={"Authorization": "Bearer dummy-llm-secret", "x-forwarded-for": ip},
    )


def spoken(resp):
    import json

    return "".join(
        json.loads(row[6:])["choices"][0]["delta"].get("content", "")
        for row in resp.text.splitlines()
        if row.startswith("data: {")
    )


def test_each_turn_uses_the_fan_ip_captured_when_context_was_minted(tmp_path, monkeypatch):
    client, provider, _, _ = app_for(tmp_path, monkeypatch, asks_per_hour=3)
    with client:
        ctx = mint(client, start_replay(client), ip="198.51.100.7")
        responses = [turn(client, ctx, ip=f"203.0.113.{i}") for i in range(1, 4)]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert len(provider.requests) == 2


def test_a_paid_stream_is_recorded_and_the_next_turn_sees_the_daily_cap(tmp_path, monkeypatch):
    client, provider, store, guard = app_for(tmp_path, monkeypatch, daily_budget=0.000001)
    with client:
        ctx = mint(client, start_replay(client))
        first = turn(client, ctx)
        rows_after_first = store.all("answers")
        spent_after_first = guard.spent_today(store)
        second = turn(client, ctx)

    assert first.status_code == 200 and "So far," in spoken(first)
    assert len(rows_after_first) == 1
    row = rows_after_first[0]
    assert row["replay_id"]
    assert row["model"] == commentator.MODEL
    assert row["tokens_in"] > 0 and row["tokens_out"] > 0
    assert row["mubit_request_ids"] == ["fake-1"]
    assert spent_after_first >= guard.budget
    assert second.status_code == 200 and "off air for today" in spoken(second).lower()
    assert len(provider.requests) == 1
    assert len(store.all("answers")) == 1


def test_streaming_tap_keeps_the_mubit_request_id():
    message = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="A checked answer.")],
        usage=SimpleNamespace(input_tokens=11, output_tokens=4),
    )

    class Stream:
        response = SimpleNamespace(headers={"X-Middleware-Request-Id": "mubit-123"})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __iter__(self):
            return iter(())

        def get_final_message(self):
            return message

    inner = SimpleNamespace(
        client=SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: Stream()))
    )
    tap = converse.Tap(inner, lambda _: None, lambda: None)

    assert tap.call({"messages": []}) == {
        "content": [{"type": "text", "text": "A checked answer."}],
        "usage": {"input_tokens": 11, "output_tokens": 4},
        "request_id": "mubit-123",
    }


def test_missing_provider_usage_is_not_fabricated(tmp_path, monkeypatch):
    client, provider, store, _ = app_for(tmp_path, monkeypatch, usage=False)
    with client:
        ctx = mint(client, start_replay(client))
        response = turn(client, ctx)

    assert response.status_code == 200 and "So far," in spoken(response)
    assert len(provider.requests) == 1
    assert store.all("answers") == []
