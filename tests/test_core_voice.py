import json
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
    assert b"Kohli! Six over long-on!" in req.content and b"eleven_v3" in req.content
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


def test_warm_speaks_once_in_every_voice():
    from core.voice import VOICES, warm

    seen = []
    took = warm(KEY, transport=upstream(seen=seen))
    assert set(took) == {v["id"] for v in VOICES}
    assert {r.url.path.split("/")[3] for r in seen} == {v["eleven_id"] for v in VOICES}
    assert all(r.headers["xi-api-key"] == KEY for r in seen)


def test_warm_reports_a_voice_that_fails():
    from core.voice import warm

    took = warm(KEY, transport=upstream(status=401))
    assert all(ms is None for ms in took.values())


@pytest.mark.parametrize(
    "moment,tag",
    [
        ({"type": "Shot", "outcome": "Goal"}, "[shouting]"),
        ({"type": "Wicket", "outcome": "caught"}, "[shouting]"),
        ({"type": "Six", "outcome": "6 runs"}, "[shouting]"),
        ({"type": "Last ball", "outcome": "1 run"}, "[shouting]"),
        ({"type": "Shot", "outcome": "Saved"}, "[excited]"),
        ({"type": "Four", "outcome": "4 runs"}, "[excited]"),
        ({"type": "Chase", "outcome": "dot ball"}, "[hushed]"),
        ({"type": "Substitution", "outcome": "Tactical"}, None),
    ],
)
def test_moment_kind_sets_the_audio_tag(moment, tag):
    from core.voice import tag_for

    assert tag_for(moment) == tag


def by_model(seen, fail=()):
    """Upstream that answers 500 for every model in `fail`; records (model, text) per call."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((body["model_id"], body["text"]))
        return httpx.Response(500 if body["model_id"] in fail else 200, content=AUDIO)

    return httpx.MockTransport(handle)


def replay_wicket(tmp_path, transport):
    moments = [{"sport": "cricket", "match_id": "c1", "idx": 0, "clock": "19.6", "type": "Wicket"}]

    def commentate(moment, history):
        return {"line_id": "w1", "sport": "cricket", "text": "Gone! Kohli's out!"}

    store = Store(tmp_path)
    deps = Deps(lambda: [], lambda mid: moments, commentate)
    client = TestClient(create_app(store=store, deps=deps, tts_transport=transport))
    return client, store


def test_line_is_voiced_with_its_tag_when_created_and_the_tag_is_never_stored(
    tmp_path, monkeypatch
):
    from core.smoke import read_stream

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    client, store = replay_wicket(tmp_path, by_model(seen))
    with client:
        rid = client.post("/replays", json={"match_id": "c1", "speed": 1e6}).json()["replay_id"]
        events = read_stream(client, rid)
        first = client.get("/lines/w1/audio")
        again = client.get("/lines/w1/audio")
    assert first.content == AUDIO and again.content == AUDIO
    assert seen == [("eleven_v3", "[shouting] Gone! Kohli's out!")]  # made once, then cached
    assert store.all("lines")[0]["text"] == "Gone! Kohli's out!"
    assert all("[" not in json.dumps(d) for _, d in events)


def test_v3_retries_once_then_falls_back_to_flash_without_the_tag(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    caplog.set_level(logging.DEBUG)
    seen = []
    client, _ = replay_wicket(tmp_path, by_model(seen, fail={"eleven_v3"}))
    with client:
        from core.smoke import read_stream

        read_stream(client, client.post("/replays", json={"match_id": "c1"}).json()["replay_id"])
        resp = client.get("/lines/w1/audio")
    assert resp.status_code == 200
    assert [m for m, _ in seen] == ["eleven_v3", "eleven_v3", "eleven_flash_v2_5"]
    assert seen[-1][1] == "Gone! Kohli's out!"
    assert "model=eleven_flash_v2_5" in caplog.text and KEY not in caplog.text


def test_v3_that_would_land_late_goes_straight_to_flash(monkeypatch):
    import asyncio
    import time

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    speaker = Speaker(by_model(seen))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}

    async def run():
        speaker.prepare(line, {"type": "Shot", "outcome": "Goal"}, time.monotonic() + 1.0)
        return await speaker.audio(line, VOICES[1])

    assert asyncio.run(run()) == (AUDIO, "eleven_flash_v2_5")
    assert seen == [("eleven_flash_v2_5", "Goal!")]


def test_voice_and_model_per_sport_come_from_env(tmp_path, monkeypatch):
    from core.voice import VOICES

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("VOICE_FOOTBALL", "george")
    monkeypatch.setenv("VOICE_MODEL_FOOTBALL", "eleven_flash_v2_5")
    seen = []
    line = {"line_id": "f1", "sport": "football", "text": "Goal!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        defaults = {v["id"]: v["default_for"] for v in client.get("/voices").json()}
        assert client.get("/lines/f1/audio").status_code == 200
    george = next(v for v in VOICES if v["id"] == "george")
    assert voice_in(seen[0]) == george["eleven_id"] and b"eleven_flash_v2_5" in seen[0].content
    assert defaults == {"george": "football", "connor": None, "viraj": "cricket"}


def test_a_raw_elevenlabs_voice_id_is_a_config_only_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("VOICE_FOOTBALL", "gU0LNdkMOQCOrPrwtbee")
    seen = []
    line = {"line_id": "f1", "sport": "football", "text": "Goal!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        voices = {v["id"]: v for v in client.get("/voices").json()}
        assert client.get("/lines/f1/audio").status_code == 200
        assert client.get("/lines/f1/audio?voice=football-pick").status_code == 200
    assert voices["football-pick"]["default_for"] == "football"
    assert voices["football-pick"]["lang"] == "en-GB" and voices["connor"]["default_for"] is None
    assert "gU0LNdkMOQCOrPrwtbee" not in json.dumps(list(voices.values()))
    assert [voice_in(r) for r in seen] == ["gU0LNdkMOQCOrPrwtbee"]  # the second request is cached


def test_empty_voice_settings_from_env_example_keep_the_defaults(monkeypatch):
    from core.voice import default_voice, model_for

    for name in ("VOICE_FOOTBALL", "VOICE_MODEL_FOOTBALL"):
        monkeypatch.setenv(name, "")
    assert default_voice("football")["id"] == "connor" and model_for("football") == "eleven_v3"
