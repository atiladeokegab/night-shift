"""Talk streams preserve actual model usage and request IDs for the daily budget."""

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


def app_for(tmp_path, monkeypatch, *, daily_budget=50.0):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    async def signed_url(*_):
        return "wss://example.test/conversation"

    monkeypatch.setattr(converse, "signed_url", signed_url)
    provider = FakeProvider()
    monkeypatch.setattr(commentator, "unrecorded_provider", lambda: provider)

    def ask(question, past, lines, provider=None, **kwargs):
        return answer(
            question,
            past,
            lines,
            header=HEADER,
            provider=provider or commentator.unrecorded_provider(),
            **kwargs,
        )

    store = Store(tmp_path)
    guard = Guard(
        env={
            "ASKS_PER_HOUR": "20",
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


def sdk_stream():
    class Stream:
        response = SimpleNamespace(headers={"X-Middleware-Request-Id": "streamed-123"})

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __iter__(self):
            yield SimpleNamespace(type="text", text="Player1 scored for the Reds.")

        def get_final_message(self):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Player1 scored for the Reds.")],
                usage=SimpleNamespace(input_tokens=11, output_tokens=7),
            )

    class Messages:
        calls = 0

        def stream(self, **_):
            self.calls += 1
            return Stream()

    messages = Messages()
    sdk = SimpleNamespace(client=SimpleNamespace(messages=messages))
    return sdk, messages


def test_actual_sdk_stream_usage_and_request_id_are_recorded(tmp_path, monkeypatch):
    client, _, store, _ = app_for(tmp_path, monkeypatch)
    sdk, messages = sdk_stream()
    monkeypatch.setattr(commentator, "unrecorded_provider", lambda: sdk)

    with client:
        ctx = mint(client, start_replay(client))
        first = turn(client, ctx)
        row = store.all("answers")[0]

    assert first.status_code == 200 and "Player1 scored for the Reds." in spoken(first)
    assert row["replay_id"]
    assert row["model"] == commentator.MODEL
    assert row["tokens_in"] == 11 and row["tokens_out"] == 7
    assert row["mubit_request_ids"] == ["streamed-123"]


def test_talk_stream_refreshes_spend_cache_before_next_turn(tmp_path, monkeypatch):
    client, _, store, guard = app_for(tmp_path, monkeypatch, daily_budget=0.000001)
    sdk, messages = sdk_stream()
    monkeypatch.setattr(commentator, "unrecorded_provider", lambda: sdk)

    with client:
        ctx = mint(client, start_replay(client))
        first = turn(client, ctx)
        second = turn(client, ctx)
        spent_after_first = guard.spent_today(store)

    assert first.status_code == 200 and "Player1 scored for the Reds." in spoken(first)
    assert second.status_code == 200 and "off air for today" in spoken(second).lower()
    assert messages.calls == 1
    assert len(store.all("answers")) == 1
    assert spent_after_first >= guard.budget


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
