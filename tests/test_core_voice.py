import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.store import Store

KEY = "sk-test-not-a-real-key"
AUDIO = b"ID3fake-mp3-bytes" * 64


def upstream(status=200, body=AUDIO, seen=None):
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handle)


def client_for(tmp_path, transport):
    store = Store(tmp_path)
    store.append("lines", {"line_id": "l1", "text": "Kohli! Six over long-on!"})
    deps = Deps(lambda: [], lambda mid: [], lambda m, h: {})
    return TestClient(create_app(store=store, deps=deps, tts_transport=transport))


def test_line_streams_audio_and_logs_first_byte(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    caplog.set_level(logging.INFO, logger="night_shift.voice")
    with client_for(tmp_path, upstream(seen=seen)) as client:
        resp = client.get("/lines/l1/audio")
    assert resp.status_code == 200 and resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == AUDIO
    req = seen[0]
    assert req.headers["xi-api-key"] == KEY
    assert b"Kohli! Six over long-on!" in req.content and b"eleven_flash_v2_5" in req.content
    assert "voice line=l1 first_byte_ms=" in caplog.text
    assert KEY not in caplog.text and KEY.encode() not in resp.content


def test_no_key_is_503(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with client_for(tmp_path, upstream()) as client:
        assert client.get("/lines/l1/audio").status_code == 503


@pytest.mark.parametrize("status,body", [(401, b'{"detail":"bad key"}'), (500, b""), (200, b"")])
def test_upstream_failure_is_503_without_the_key(tmp_path, monkeypatch, caplog, status, body):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    caplog.set_level(logging.DEBUG)
    with client_for(tmp_path, upstream(status, body)) as client:
        resp = client.get("/lines/l1/audio")
    assert resp.status_code == 503
    assert KEY not in resp.text and KEY not in caplog.text


def test_upstream_unreachable_is_503(tmp_path, monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    with client_for(tmp_path, httpx.MockTransport(down)) as client:
        assert client.get("/lines/l1/audio").status_code == 503


def test_unknown_line_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    with client_for(tmp_path, upstream()) as client:
        assert client.get("/lines/nope/audio").status_code == 404
