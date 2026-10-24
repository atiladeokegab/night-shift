"""#401: no silent fallback. /health and /stats say Mubit is degraded when its key is unset or its
last call failed, from that call's outcome: nothing probes Mubit."""

import logging

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from agent import commentator
from agent.commentator import MubitProvider, mubit_status
from core.app import create_app
from core.store import Store


def engine_unavailable():
    request = httpx.Request("POST", "https://mubit.example/v1/messages")
    body = {"type": "error", "error": {"type": "engine_unavailable", "message": "no engine"}}
    return anthropic.APIStatusError(
        "engine unavailable", response=httpx.Response(503, request=request), body=body
    )


@pytest.fixture(autouse=True)
def no_last_call(monkeypatch):
    monkeypatch.setattr(commentator, "_last_error", None)


def test_no_key_is_degraded_and_warned_at_startup(tmp_path, monkeypatch, caplog):
    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="touchline.app"):
        client = TestClient(create_app(store=Store(tmp_path)))
    assert "MUBIT_API_KEY unset" in caplog.text
    degraded = {"mubit": "degraded", "mubit_reason": "MUBIT_API_KEY unset"}
    assert client.get("/health").json() == {"status": "ok", **degraded}
    stats = client.get("/stats").json()
    assert {k: stats[k] for k in degraded} == degraded


def test_a_503_engine_unavailable_is_degraded_until_a_call_succeeds(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("MUBIT_API_KEY", "test-key")
    with caplog.at_level(logging.WARNING, logger="touchline.app"):
        client = TestClient(create_app(store=Store(tmp_path)))
    assert "MUBIT_API_KEY unset" not in caplog.text
    assert client.get("/health").json()["mubit"] == "ok"  # no call yet: nothing failed

    provider = MubitProvider("test-key")

    def unavailable(client, request):
        raise engine_unavailable()

    monkeypatch.setattr(provider, "_stream", unavailable)
    with pytest.raises(anthropic.APIStatusError):
        provider.call({})
    degraded = {"mubit": "degraded", "mubit_reason": "503 engine_unavailable"}
    assert client.get("/health").json() == {"status": "ok", **degraded}
    stats = client.get("/stats").json()
    assert {k: stats[k] for k in degraded} == degraded

    monkeypatch.setattr(provider, "_stream", lambda client, request: {"content": []})
    provider.call({})
    assert client.get("/health").json()["mubit"] == "ok"
    assert client.get("/stats").json()["mubit_reason"] is None


def test_a_call_that_never_answered_names_its_type_never_its_message(monkeypatch):
    monkeypatch.setenv("MUBIT_API_KEY", "test-key")
    provider = MubitProvider("test-key")

    def timed_out(client, request):
        raise anthropic.APITimeoutError(httpx.Request("POST", "https://mubit.example/v1/messages"))

    monkeypatch.setattr(provider, "_stream", timed_out)
    with pytest.raises(anthropic.APITimeoutError):
        provider.call({})
    assert mubit_status() == {"mubit": "degraded", "mubit_reason": "APITimeoutError"}
