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


def client_for(tmp_path, transport, *lines):
    store = Store(tmp_path)
    for line in ({"line_id": "l1", "text": "Kohli! Six over long-on!"}, *lines):
        store.append("lines", line)
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


@pytest.mark.parametrize(
    "exc", [httpx.ConnectError, httpx.ReadTimeout], ids=["unreachable", "cold-voice-timeout"]
)
def test_upstream_failure_is_503(tmp_path, monkeypatch, exc):
    def down(request):
        raise exc("upstream", request=request)

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    with client_for(tmp_path, httpx.MockTransport(down)) as client:
        assert client.get("/lines/l1/audio").status_code == 503


def test_unknown_line_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    with client_for(tmp_path, upstream()) as client:
        assert client.get("/lines/nope/audio").status_code == 404


def voice_in(request: httpx.Request) -> str:
    return request.url.path.split("/")[3]


def test_voices_lists_one_default_per_sport(tmp_path):
    with client_for(tmp_path, upstream()) as client:
        voices = client.get("/voices").json()
    assert {v["default_for"] for v in voices} >= {"cricket", "football"}
    assert all(set(v) == {"id", "label", "default_for", "lang"} for v in voices)
    lang = {v["default_for"]: v["lang"] for v in voices}
    assert lang["cricket"] == "en-IN" and lang["football"] == "en-GB"
    assert all(v["id"].isascii() and " " not in v["id"] for v in voices)


@pytest.mark.parametrize("sport", ["cricket", "football"])
def test_audio_defaults_to_the_lines_sport_voice(tmp_path, monkeypatch, sport):
    from core.voice import VOICES

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    line = {"line_id": "s1", "sport": sport, "text": "Out!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        assert client.get("/lines/s1/audio").status_code == 200
    default = next(v for v in VOICES if v["default_for"] == sport)
    assert voice_in(seen[0]) == default["eleven_id"]


def test_audio_uses_the_chosen_voice(tmp_path, monkeypatch):
    from core.voice import VOICES

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    chosen = next(v for v in VOICES if v["default_for"] == "football")
    line = {"line_id": "c1", "sport": "cricket", "text": "Six!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        assert client.get(f"/lines/c1/audio?voice={chosen['id']}").status_code == 200
    assert voice_in(seen[0]) == chosen["eleven_id"]


def test_unknown_voice_is_404_before_calling_upstream(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    with client_for(tmp_path, upstream(seen=seen)) as client:
        resp = client.get("/lines/l1/audio?voice=JBFqnCBsd6RMkjVDRZzb")
    assert resp.status_code == 404 and seen == []
