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
    caplog.set_level(logging.INFO, logger="touchline.voice")
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
    assert all(set(v) <= {"id", "label", "default_for", "lang", "analyst_for"} for v in voices)
    analysts = {s: v["id"] for v in voices for s in v.get("analyst_for", [])}  # ANALYST_FOR
    assert analysts == {"cricket": "george", "football": "sam", "basketball": "george", "f1": "sam"}
    lang = {v["default_for"]: v["lang"] for v in voices}
    assert lang["cricket"] == "en-IN" and lang["football"] == "en-GB"
    assert lang["basketball"] == "en-US"  # Sam, the American play-by-play pick
    assert all(v["id"].isascii() and " " not in v["id"] for v in voices)


@pytest.mark.parametrize("sport", ["cricket", "football", "basketball"])
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


def test_warm_covers_the_sport_picks_once_per_elevenlabs_voice(caplog, capsys):
    from core.voice import FALLBACK_MODEL, MODEL, VOICES, warm

    env = {
        "VOICE_FOOTBALL": "gU0LNdkMOQCOrPrwtbee",  # the announcer's voice, also f1's default
        "VOICE_CRICKET": "IX4AgWzTnD6q0cNvHqvK",  # Raju: a raw library id
        "VOICE_MODEL_CRICKET": "eleven_turbo_v2_5",
    }
    seen = []
    caplog.set_level(logging.DEBUG)
    took = warm(KEY, transport=upstream(seen=seen), env=env)
    assert {"football-pick", "cricket-pick"} <= set(took) and None not in took.values()
    calls = [(r.url.path.split("/")[3], json.loads(r.content)["model_id"]) for r in seen]
    assert len(calls) == len(set(calls))  # the announcer's voice is not spoken twice
    assert set(calls) == {(v["eleven_id"], m) for v in VOICES for m in (MODEL, FALLBACK_MODEL)} | {
        (eleven_id, model)
        for eleven_id in ("IX4AgWzTnD6q0cNvHqvK", "PdJQAOWyIMAQwD7gQcSc")  # Raju, and Viraj
        for model in (MODEL, "eleven_turbo_v2_5", FALLBACK_MODEL)  # the cricket model too
    }
    assert KEY not in caplog.text + capsys.readouterr().out


def test_warm_reads_only_voice_settings_from_dotenv(tmp_path):
    from core.voice import env_with_dotenv

    dotenv = tmp_path / ".env"
    dotenv.write_text("ELEVENLABS_API_KEY=sk-LEAK\nVOICE_CRICKET='IX4AgWzTnD6q0cNvHqvK'\n")
    env = env_with_dotenv(dotenv, env={"VOICE_FOOTBALL": "george"})
    assert env == {"VOICE_FOOTBALL": "george", "VOICE_CRICKET": "IX4AgWzTnD6q0cNvHqvK"}


def test_warm_reports_a_voice_that_fails():
    from core.voice import warm

    took = warm(KEY, transport=upstream(status=401))
    assert all(ms is None for ms in took.values())


def hoop(kind, outcome, period=2, clock="06:00", **detail):
    return {
        "sport": "basketball",
        "type": kind,
        "outcome": outcome,
        "period": period,
        "clock": clock,
        "detail": detail,
    }


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
        (hoop("Field goal", "2 points", period=4, clock="00:05"), "[shouting]"),
        (hoop("Free throw", "1 point", lead_change=True), "[shouting]"),
        (hoop("Field goal", "2 points", play="Bryant Slam Dunk (51 PTS)"), "[shouting]"),
        (hoop("Field goal", "3 points"), "[shouting]"),
        (hoop("End of game", "Final buzzer", period=4, clock="00:00"), "[shouting]"),
        (hoop("Steal", "Steal", period=4, clock="00:18"), "[excited]"),
        (hoop("Free throw", "1 point", period=4, clock="00:43"), "[excited]"),
        (hoop("Field goal", "2 points"), None),  # a routine basket mid-game stays plain
        ({"sport": "f1", "type": "Lead change", "outcome": "P1 on track"}, "[shouting]"),
        ({"sport": "f1", "type": "Red flag", "outcome": "Red flag"}, "[shouting]"),
        ({"sport": "f1", "type": "Finish", "outcome": "chequered flag"}, "[shouting]"),
        ({"sport": "f1", "type": "Overtake", "outcome": "P3 on track"}, "[excited]"),
        ({"sport": "f1", "type": "Pit stop", "outcome": "pits for soft tyres"}, "[excited]"),
        ({"sport": "f1", "type": "Safety car", "outcome": "Safety car deployed"}, "[excited]"),
        ({"sport": "f1", "type": "Last lap", "outcome": "final lap"}, "[hushed]"),
        ({"sport": "f1", "type": "Retirement", "outcome": "out on lap 34"}, None),
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


def test_v3_for_a_moment_a_second_away_is_still_tried(monkeypatch):
    # was: straight to flash. 00037 played one line in five flat that way (#57).
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

    assert asyncio.run(run()) == (AUDIO, "eleven_v3")
    assert [model for model, _ in seen] == ["eleven_v3"]


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
    assert defaults == {
        "george": "football",
        "connor": None,
        "viraj": "cricket",
        "sam": "basketball",
        "announcer": "f1",
    }


def test_a_raw_elevenlabs_voice_id_is_a_config_only_pick(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("VOICE_FOOTBALL", "onwK4e9ZLuTAKqWW03F9")
    seen = []
    line = {"line_id": "f1", "sport": "football", "text": "Goal!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        voices = {v["id"]: v for v in client.get("/voices").json()}
        assert client.get("/lines/f1/audio").status_code == 200
        assert client.get("/lines/f1/audio?voice=football-pick").status_code == 200
    assert voices["football-pick"]["default_for"] == "football"
    assert voices["football-pick"]["lang"] == "en-GB" and voices["connor"]["default_for"] is None
    assert "onwK4e9ZLuTAKqWW03F9" not in json.dumps(list(voices.values()))
    assert [voice_in(r) for r in seen] == ["onwK4e9ZLuTAKqWW03F9"]  # the second request is cached


def test_the_deployed_picks_give_every_sport_its_own_default(tmp_path, monkeypatch):
    # The live env: football's pick is the announcer's ElevenLabs id, which is also f1's default.
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("VOICE_FOOTBALL", "gU0LNdkMOQCOrPrwtbee")
    monkeypatch.setenv("VOICE_CRICKET", "IX4AgWzTnD6q0cNvHqvK")
    seen = []
    line = {"line_id": "f1", "sport": "football", "text": "Goal!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        voices = client.get("/voices").json()
        assert client.get("/lines/f1/audio?voice=football-pick").status_code == 200
    defaults = {v["default_for"]: v["id"] for v in voices if v["default_for"]}
    assert defaults == {
        "football": "football-pick",
        "cricket": "cricket-pick",
        "f1": "announcer",
        "basketball": "sam",
    }
    # football's pick is the announcer: the sheet lists it once, and only for the repeat
    repeats = {v["id"]: v["same_as"] for v in voices if "same_as" in v}
    assert repeats == {"football-pick": "announcer"}
    assert [voice_in(r) for r in seen] == ["gU0LNdkMOQCOrPrwtbee"]


def test_a_pick_is_labelled_by_voice_label_else_as_the_sports_pick(monkeypatch):
    from core.voice import all_voices

    monkeypatch.delenv("VOICE_LABEL_FOOTBALL", raising=False)
    monkeypatch.setenv("VOICE_FOOTBALL", "gU0LNdkMOQCOrPrwtbee")
    monkeypatch.setenv("VOICE_CRICKET", "IX4AgWzTnD6q0cNvHqvK")
    monkeypatch.setenv("VOICE_LABEL_CRICKET", "Raju, Cricket Commentator")
    labels = {v["id"]: v["label"] for v in all_voices()}
    assert labels["cricket-pick"] == "Raju, Cricket Commentator"
    assert labels["football-pick"] == "Football pick"


def test_every_default_shows_its_voices_own_name_and_f1_reads_as_football(monkeypatch):
    from core.voice import all_voices

    monkeypatch.delenv("VOICE_LABEL_FOOTBALL", raising=False)
    monkeypatch.setenv("VOICE_FOOTBALL", "announcer")
    labels = {v["id"]: v["label"] for v in all_voices()}
    assert labels["sam"] == "Sam, Engaging Game Narrator"  # whole on the page: no "Voice: American"
    assert labels["announcer"] == labels["football-pick"] == "British Football Announcer"


def test_a_pick_by_another_sports_default_id_gets_its_own_entry(tmp_path, monkeypatch):
    # docs/voice.md's own id for the pick: the announcer is already f1's default
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("VOICE_FOOTBALL", "announcer")
    seen = []
    line = {"line_id": "f1", "sport": "football", "text": "Goal!"}
    with client_for(tmp_path, upstream(seen=seen), line) as client:
        voices = client.get("/voices").json()
        assert client.get("/lines/f1/audio").status_code == 200
    defaults = {v["default_for"]: v["id"] for v in voices if v["default_for"]}
    assert defaults["football"] == "football-pick" and defaults["f1"] == "announcer"
    assert [voice_in(r) for r in seen] == ["gU0LNdkMOQCOrPrwtbee"]


def test_empty_voice_settings_from_env_example_keep_the_defaults(monkeypatch):
    from core.voice import default_voice, model_for

    for name in ("VOICE_FOOTBALL", "VOICE_MODEL_FOOTBALL"):
        monkeypatch.setenv(name, "")
    assert default_voice("football")["id"] == "connor" and model_for("football") == "eleven_v3"


class Trickle(httpx.AsyncByteStream):
    """20 chunks 0.03 s apart, the first after `wait` s: each read is quick, the whole body is
    not."""

    def __init__(self, wait=0.03):
        self.wait = wait

    async def __aiter__(self):
        import asyncio

        await asyncio.sleep(self.wait)
        for _ in range(20):
            yield AUDIO[:4]
            await asyncio.sleep(0.03)


def trickled_v3(monkeypatch, wait):
    """What audio() gives for a line due 0.08 s after the flash reserve, v3 trickling in after
    `wait` s and flash answering at once."""
    import asyncio
    import time

    from core import voice
    from core.voice import FALLBACK_RESERVE_S, VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(voice, "PREPARED_V3_S", 0.0)  # only the deadline bounds v3 here
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model_id"]
        seen.append(model)
        return (
            httpx.Response(200, stream=Trickle(wait))
            if "v3" in model
            else httpx.Response(200, content=AUDIO)
        )

    speaker = Speaker(httpx.MockTransport(handle))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}

    async def run():
        speaker.prepare(line, {"type": "Shot"}, time.monotonic() + FALLBACK_RESERVE_S + 0.08)
        return await speaker.audio(line, VOICES[1])

    return asyncio.run(run()), seen


def test_a_stream_that_starts_in_time_plays_on_past_the_deadline(monkeypatch):
    # the page plays from the first chunk, so only that has to beat the deadline
    made, seen = trickled_v3(monkeypatch, wait=0.03)
    assert made == (AUDIO[:4] * 20, "eleven_v3") and seen == ["eleven_v3"]


def test_a_stream_whose_first_chunk_misses_the_deadline_falls_back(monkeypatch):
    # httpx's timeout is per read, so only a deadline on the call stops a slow first chunk
    made, seen = trickled_v3(monkeypatch, wait=0.3)
    assert made == (AUDIO, "eleven_flash_v2_5")
    assert seen[0] == "eleven_v3" and seen[-1] == "eleven_flash_v2_5"


def test_audio_is_ready_at_the_first_chunk_and_the_page_gets_every_chunk(tmp_path, monkeypatch):
    # the moment-to-audio time stops at the first chunk, not after the whole file (0.6 s here)
    import asyncio
    import time

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    store = Store(tmp_path)
    speaker = Speaker(httpx.MockTransport(lambda r: httpx.Response(200, stream=Trickle())), store)
    line = {"line_id": "x", "sport": "football", "text": "Goal!", "replay_id": "r1"}

    async def run():
        line["moment_at"] = time.monotonic()
        speaker.prepare(line, {"type": "Goal"}, time.monotonic() + 5.0)
        clip = await speaker.stream(line, VOICES[1])
        ready = time.monotonic() - line["moment_at"]
        assert not clip.whole and clip.model == "eleven_v3"
        return ready, b"".join([chunk async for chunk in clip.follow()]), clip

    ready, heard, clip = asyncio.run(run())
    assert ready < 0.3 and heard == AUDIO[:4] * 20 and clip.whole
    [said] = store.all("voice")
    assert said["audio_first_ms"] < 300 and said["model"] == "eleven_v3"


def test_the_route_streams_a_line_still_arriving(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    trickle = httpx.MockTransport(lambda r: httpx.Response(200, stream=Trickle()))
    with client_for(tmp_path, trickle) as client:
        first = client.get("/lines/l1/audio")
        again = client.get("/lines/l1/audio")  # whole by now: a plain file
    assert first.status_code == 200 and first.headers["content-type"] == "audio/mpeg"
    assert "content-length" not in first.headers and first.content == AUDIO[:4] * 20
    assert again.headers["content-length"] == str(len(AUDIO[:4] * 20))


IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) CriOS/126.0 Mobile/15E148 Safari/604.1"
)
MAC_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    " Version/17.5 Safari/605.1.15"
)
CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/126.0.0.0 Safari/537.36"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko)"
    " Version/4.0 Mobile Safari/537.36"
)


@pytest.mark.parametrize(
    "agent,whole", [(IPHONE, True), (MAC_SAFARI, True), (CHROME, False), (ANDROID, False)]
)
def test_safari_gets_the_whole_file_and_everyone_else_the_stream(
    tmp_path, monkeypatch, agent, whole
):
    # Safari may not play a chunked mp3 with no length: it waits for the finished clip
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    trickle = httpx.MockTransport(lambda r: httpx.Response(200, stream=Trickle()))
    with client_for(tmp_path, trickle) as client:
        resp = client.get("/lines/l1/audio", headers={"user-agent": agent})
    assert resp.status_code == 200 and resp.content == AUDIO[:4] * 20
    assert ("content-length" in resp.headers) == whole


def test_safari_is_safari_or_any_iphone_or_ipad_browser():
    from core.voice import safari

    assert safari(MAC_SAFARI) and safari(IPHONE)  # IPHONE is Chrome on iOS: still Safari's engine
    assert safari("Mozilla/5.0 (iPad; CPU OS 17_5) FxiOS/127.0 Mobile/15E148 Safari/605.1.15")
    assert not safari(CHROME) and not safari(ANDROID) and not safari(None)
    assert not safari("Mozilla/5.0 (Macintosh) FxiOS/127.0 Safari/605.1.15")
    assert not safari("Mozilla/5.0 (X11; Linux) Chromium/126.0 Safari/537.36")


def test_safari_gets_a_503_not_half_a_line_when_the_stream_breaks(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    breaks = httpx.MockTransport(lambda r: httpx.Response(200, stream=Breaks()))
    with client_for(tmp_path, breaks) as client:
        assert client.get("/lines/l1/audio", headers={"user-agent": MAC_SAFARI}).status_code == 503


class Breaks(httpx.AsyncByteStream):
    """One chunk, then the connection drops."""

    async def __aiter__(self):
        yield AUDIO[:4]
        raise httpx.ReadError("connection reset")


def test_a_stream_cut_off_after_its_first_chunk_is_not_replaced_mid_line(monkeypatch):
    # the page may be playing it: flash after half a v3 line would say it twice; the next ask
    # makes it again
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["model_id"])
        if len(seen) == 1:
            return httpx.Response(200, stream=Breaks())
        return httpx.Response(200, content=AUDIO)

    speaker = Speaker(httpx.MockTransport(handle))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}

    async def run():
        cut = await speaker.audio(line, VOICES[1])
        assert seen == ["eleven_v3"] and ("x", VOICES[1]["id"]) not in speaker.jobs
        return cut, await speaker.audio(line, VOICES[1])

    assert asyncio.run(run()) == (None, (AUDIO, "eleven_v3"))


def test_a_prepared_lines_v3_call_gets_the_longer_timeout_and_a_live_one_its_deadline(
    monkeypatch,
):
    # 00037: the first line of each replay is due 5 s in, ready at ~2 s, so v3 had ~1.5 s
    import asyncio
    import time

    from core.voice import FALLBACK_RESERVE_S, LIVE_BUDGET_S, PREPARED_V3_S, VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    timeouts = []
    timeout = asyncio.timeout

    def bound(delay):
        timeouts.append(delay)
        return timeout(delay)

    monkeypatch.setattr(asyncio, "timeout", bound)
    models = []

    def handle(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model_id"]
        models.append(model)
        return httpx.Response(200, content=AUDIO)

    speaker = Speaker(httpx.MockTransport(handle))
    prepared = {"line_id": "a", "sport": "football", "text": "Goal!"}
    live = {"line_id": "b", "sport": "football", "text": "Goal!"}

    async def run():
        speaker.prepare(prepared, {"type": "Goal"}, time.monotonic() + 3.0)
        await speaker.audio(prepared, VOICES[1])
        await speaker.audio(live, VOICES[1])

    asyncio.run(run())
    ahead, now = timeouts
    assert models == ["eleven_v3", "eleven_v3"]
    assert PREPARED_V3_S - 0.5 < ahead <= PREPARED_V3_S  # past its moment: late v3 beats flash
    assert now <= LIVE_BUDGET_S - FALLBACK_RESERVE_S  # the request-started line keeps its deadline


def test_a_prepared_line_makes_one_v3_call_before_flash(monkeypatch):
    import asyncio
    import time

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model_id"]
        seen.append(model)
        return httpx.Response(500 if "v3" in model else 200, content=AUDIO)

    speaker = Speaker(httpx.MockTransport(handle))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}

    async def run():
        speaker.prepare(line, {"type": "Goal"}, time.monotonic() + 3.0)
        return await speaker.audio(line, VOICES[1])

    assert asyncio.run(run()) == (AUDIO, "eleven_flash_v2_5")
    assert seen == ["eleven_v3", "eleven_flash_v2_5"]


def test_audio_made_ahead_that_failed_is_tried_again_when_the_page_asks(monkeypatch):
    # /stage replays at speed 10 and shows a line every 6 s: a line's audio is made as it arrives,
    # and if that failed, the page's request comes long after, so it must not get the stale 503.
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model_id"])
        return httpx.Response(500 if len(calls) <= 3 else 200, content=AUDIO)  # v3, v3, flash fail

    speaker = Speaker(httpx.MockTransport(handle))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}

    async def run():
        speaker.prepare(line, {"type": "Shot"})
        await speaker.jobs["x", VOICES[1]["id"]]  # the page asks later
        return await speaker.audio(line, VOICES[1])

    assert asyncio.run(run()) == (AUDIO, "eleven_v3")
    assert len(calls) == 4


def test_audio_the_request_started_is_not_tried_twice(monkeypatch):
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    speaker = Speaker(upstream(500, b"", seen=seen))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}
    assert asyncio.run(speaker.audio(line, VOICES[1])) is None
    # v3, v3, flash, then flash once more: then 503, and the next request tries again
    assert [json.loads(r.content)["model_id"] for r in seen] == [
        "eleven_v3",
        "eleven_v3",
        "eleven_flash_v2_5",
        "eleven_flash_v2_5",
    ]


def test_a_line_that_failed_before_any_audio_gets_one_short_flash_try_before_the_503(
    tmp_path, monkeypatch
):
    # a demo line dropped to browser speech when every call timed out once (24 Oct)
    from core import voice

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    calls, timeouts = [], []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model_id"])
        return httpx.Response(500 if len(calls) <= 3 else 200, content=AUDIO)  # v3, v3, flash fail

    real = voice.asyncio.timeout
    monkeypatch.setattr(voice.asyncio, "timeout", lambda s: timeouts.append(s) or real(s))
    with client_for(tmp_path, httpx.MockTransport(handle)) as client:
        resp = client.get("/lines/l1/audio")
    assert resp.status_code == 200 and resp.content == AUDIO
    assert calls[3:] == ["eleven_flash_v2_5"]
    assert timeouts[3] <= voice.RETRY_S  # brief: it holds one of the three TTS slots


def test_a_request_that_joins_a_prepared_job_still_running_gets_a_fresh_try(monkeypatch):
    # Hermes on #96: most /stage requests joined the job while it was still failing
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    calls = []

    async def run():
        gate = asyncio.Event()

        async def handle(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content)["model_id"])
            if len(calls) <= 3:  # the prepared job: v3, v3, flash, all failing once the gate opens
                await gate.wait()
                return httpx.Response(500)
            return httpx.Response(200, content=AUDIO)

        speaker = Speaker(httpx.MockTransport(handle))
        line = {"line_id": "x", "sport": "football", "text": "Goal!"}
        speaker.prepare(line, {"type": "Shot"})
        asked = asyncio.create_task(speaker.audio(line, VOICES[1]))
        await asyncio.sleep(0.05)
        assert not asked.done() and not speaker.jobs["x", VOICES[1]["id"]].done()
        gate.set()
        return await asked

    assert asyncio.run(run()) == (AUDIO, "eleven_v3")
    assert len(calls) == 4


def test_flash_gets_its_minimum_time_even_when_the_budget_is_spent(monkeypatch):
    import asyncio
    import time

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []
    speaker = Speaker(by_model(seen))
    line = {"line_id": "x", "sport": "football", "text": "Goal!"}

    async def run():
        speaker.prepare(line, {"type": "Shot"}, time.monotonic() - 1.0)  # v3's time has gone
        return await speaker.audio(line, VOICES[1])

    assert asyncio.run(run()) == (AUDIO, "eleven_flash_v2_5")
    assert seen == [("eleven_flash_v2_5", "Goal!")]


def test_two_waiters_on_a_failing_job_share_one_retry(monkeypatch):
    # Hermes on #96: the second waiter popped the first one's fresh retry and paid for another
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    calls = []

    async def run():
        gate = asyncio.Event()

        async def handle(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content)["model_id"])
            if len(calls) <= 3:  # hold the prepared job open until both requests wait on it
                await gate.wait()
            return httpx.Response(500)

        speaker = Speaker(httpx.MockTransport(handle))
        line = {"line_id": "x", "sport": "football", "text": "Goal!"}
        speaker.prepare(line, {"type": "Shot"})
        asked = [asyncio.create_task(speaker.audio(line, VOICES[1])) for _ in range(2)]
        await asyncio.sleep(0.05)
        gate.set()
        return await asyncio.gather(*asked)

    assert asyncio.run(run()) == [None, None]
    assert len(calls) == 6  # the prepared job (v3, v3, flash), then one shared retry


def test_a_request_waiting_on_a_dropped_job_starts_a_fresh_one(monkeypatch):
    # an abandoned replay's jobs are dropped; a page still asking gets audio, not a crash
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    calls = []

    async def run():
        gate = asyncio.Event()

        async def handle(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content)["model_id"])
            if len(calls) == 1:
                await gate.wait()  # the dropped job's call never returns
            return httpx.Response(200, content=AUDIO)

        speaker = Speaker(httpx.MockTransport(handle))
        line = {"line_id": "x", "sport": "football", "text": "Goal!"}
        speaker.prepare(line, {"type": "Shot"})
        asked = asyncio.create_task(speaker.audio(line, VOICES[1]))
        await asyncio.sleep(0.05)
        speaker.drop({"x"})
        return await asked

    assert asyncio.run(run()) == (AUDIO, "eleven_v3")
    assert len(calls) == 2


def test_an_answer_is_read_excited_on_v3_and_plainly_on_the_fallback(monkeypatch):
    # #131: a viewer's answer is spoken live; flash would read the tag aloud
    import asyncio

    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    said = {"line_id": "a1", "sport": "football", "question": "Who scores next?", "text": "Next?"}
    seen = []
    assert asyncio.run(Speaker(by_model(seen)).audio(said, VOICES[1])) == (AUDIO, "eleven_v3")
    assert seen == [("eleven_v3", "[excited] Next?")]
    seen = []
    made = asyncio.run(Speaker(by_model(seen, fail={"eleven_v3"})).audio(said, VOICES[1]))
    assert made == (AUDIO, "eleven_flash_v2_5")
    assert seen[-1] == ("eleven_flash_v2_5", "Next?")


@pytest.mark.parametrize("sport", ["football", "cricket", "basketball", "f1"])
def test_every_sport_has_an_analyst_who_sounds_like_someone_else(monkeypatch, sport):
    # #131: a second commentator; a deployed lead pick never makes the analyst the same voice
    from core.voice import analyst_voice, default_voice

    for env in ({}, {"VOICE_FOOTBALL": "gU0LNdkMOQCOrPrwtbee", "VOICE_F1": "connor"}):
        lead, analyst = default_voice(sport, env), analyst_voice(sport, env)
        assert analyst["eleven_id"] != lead["eleven_id"] and analyst["lang"] != lead["lang"]


def test_an_analyst_line_is_made_ahead_in_the_analyst_voice_with_a_calmer_tag(monkeypatch):
    import asyncio
    import time

    from core.voice import Speaker, analyst_voice

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path.split("/")[3], body["model_id"], body["text"]))
        return httpx.Response(200, content=AUDIO)

    speaker = Speaker(httpx.MockTransport(handle))
    stat = {"line_id": "s1", "sport": "basketball", "speaker": "analyst", "text": "40 tonight."}
    analyst = analyst_voice("basketball")

    async def run():
        speaker.prepare(stat, {"type": "Stat"}, time.monotonic() + 30)
        return await speaker.audio(stat, analyst)  # the page asks for the same job

    assert asyncio.run(run()) == (AUDIO, "eleven_v3")
    assert seen == [(analyst["eleven_id"], "eleven_v3", "[warmly] 40 tonight.")]


def test_the_page_gets_an_analyst_line_in_the_analyst_voice(tmp_path, monkeypatch):
    from core.voice import analyst_voice

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((request.url.path.split("/")[3], body["model_id"], body["text"]))
        return httpx.Response(500 if body["model_id"] == "eleven_v3" else 200, content=AUDIO)

    store = Store(tmp_path)
    store.append(
        "lines", {"line_id": "s2", "sport": "cricket", "speaker": "analyst", "text": "Six fours."}
    )
    client = TestClient(create_app(store=store, tts_transport=httpx.MockTransport(handle)))
    with client:
        assert client.get("/lines/s2/audio").status_code == 200
    analyst = analyst_voice("cricket")["eleven_id"]
    assert [v for v, _, _ in seen] == [analyst] * 3
    assert seen[0][2] == "[warmly] Six fours." and seen[-1] == (
        analyst,
        "eleven_flash_v2_5",
        "Six fours.",
    )


def test_only_the_last_keep_jobs_lines_audio_stays_in_memory(monkeypatch):
    import asyncio

    from core import voice
    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(voice, "KEEP_JOBS", 3)
    speaker = Speaker(upstream())

    async def run():
        for i in range(6):
            line = {"line_id": f"l{i}", "sport": "football", "text": "Goal!"}
            assert await speaker.audio(line, VOICES[1]) == (AUDIO, "eleven_v3")

    asyncio.run(run())
    assert [k[0] for k in speaker.jobs] == ["l3", "l4", "l5"]


def gated(slow_text="slow"):
    """A transport that holds every request for `slow_text` until the gate opens."""
    import asyncio

    gate = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["text"].endswith(slow_text):
            await gate.wait()
        return httpx.Response(200, content=AUDIO)

    return gate, httpx.MockTransport(handle)


def test_cached_audio_is_served_while_unfinished_jobs_fill_the_cap(monkeypatch):
    import asyncio

    from core import voice
    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(voice, "KEEP_JOBS", 2)
    done = {"line_id": "d", "sport": "football", "text": "Goal!"}

    async def run():
        gate, transport = gated()
        speaker = Speaker(transport)
        for i in range(2):  # unfinished, in 2 of the 3 slots: the cap is full
            speaker.prepare({"line_id": f"s{i}", "sport": "football", "text": "slow"}, {})
        first = await speaker.audio(done, VOICES[1])
        again = await speaker.audio(done, VOICES[1])  # its own job must not be evicted under it
        gate.set()
        return first, again

    assert asyncio.run(run()) == ((AUDIO, "eleven_v3"),) * 2


def test_jobs_that_finish_after_the_cap_filled_are_trimmed_too(monkeypatch):
    import asyncio

    from core import voice
    from core.voice import Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(voice, "KEEP_JOBS", 2)

    async def run():
        gate, transport = gated()
        speaker = Speaker(transport)
        for i in range(5):
            speaker.prepare({"line_id": f"s{i}", "sport": "football", "text": "slow"}, {})
        assert len(speaker.jobs) == 5  # unfinished jobs are never dropped
        gate.set()
        await asyncio.gather(*speaker.jobs.values())
        await asyncio.sleep(0)  # the done callbacks
        return [k[0] for k in speaker.jobs]

    assert asyncio.run(run()) == ["s3", "s4"]


QUOTA = b'{"detail": {"status": "quota_exceeded", "message": "This request exceeds your quota."}}'


def test_stats_say_when_the_voice_falls_back_and_why(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    answers = [(401, QUOTA)]

    def handle(request: httpx.Request) -> httpx.Response:
        status, body = answers[0]
        return httpx.Response(status, content=body)

    with client_for(tmp_path, httpx.MockTransport(handle)) as client:
        assert client.get("/stats").json()["voice"] == {
            "provider": "elevenlabs",
            "last_error": None,
            "since": None,
            "characters_left": None,  # this fake answers the meter with the quota error too
        }
        assert client.get("/lines/l1/audio").status_code == 503
        voice = client.get("/stats").json()["voice"]
        assert voice["provider"] == "browser" and voice["last_error"] == "quota_exceeded"
        assert voice["since"].endswith("+00:00")
        answers[0] = (200, AUDIO)  # credits added: the next line is ElevenLabs again
        assert (
            client.get("/stats").json()["voice"]["provider"] == "browser"
        )  # until a line is voiced
        assert client.get("/lines/l1/audio").status_code == 200
        assert client.get("/stats").json()["voice"]["provider"] == "elevenlabs"


@pytest.mark.parametrize(
    "answer,kind",
    [
        (
            httpx.Response(429, json={"detail": {"status": "too_many_concurrent_requests"}}),
            "too_many_concurrent_requests",
        ),
        (httpx.Response(429, content=b"slow down"), "429"),
        (httpx.Response(500, content=b""), "500"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("down"), "network"),
    ],
)
def test_each_failure_is_named(tmp_path, monkeypatch, answer, kind):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)

    def handle(request: httpx.Request) -> httpx.Response:
        if isinstance(answer, Exception):
            raise answer
        return answer

    with client_for(tmp_path, httpx.MockTransport(handle)) as client:
        assert client.get("/lines/l1/audio").status_code == 503
        assert client.get("/stats").json()["voice"]["last_error"] == kind


def test_no_key_is_browser_speech(tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with client_for(tmp_path, upstream()) as client:
        voice = client.get("/stats").json()["voice"]
    assert voice == {
        "provider": "browser",
        "last_error": "not_configured",
        "since": None,
        "characters_left": None,
    }


def test_warm_says_loudly_when_the_quota_is_gone(caplog):
    from core.voice import warm

    caplog.set_level(logging.ERROR, logger="touchline.voice")
    took = warm(KEY, transport=upstream(401, QUOTA))
    assert set(took.values()) == {None}
    loud = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(loud) == 1 and "QUOTA EXCEEDED" in loud[0].message
    caplog.clear()
    warm(KEY, transport=upstream(401, b'{"detail": {"status": "invalid_api_key"}}'))
    assert not [r for r in caplog.records if r.levelno == logging.ERROR]


BACKUP, BACKUP2 = "sk-test-backup-one", "sk-test-backup-two"
CONNOR, GEORGE = "xtw8E1CXDMtNKx4sgP7u", "JBFqnCBsd6RMkjVDRZzb"  # football's lead; free plan
GOAL = {"line_id": "g1", "sport": "football", "text": "Messi scores!"}
PAID = b'{"detail": {"status": "paid_plan_required", "message": "Free users can\'t use these."}}'


def keyed(answers, seen):
    """A fake ElevenLabs: answers[(key, voice id)] -> (status, body), audio for anything else."""

    def handle(request: httpx.Request) -> httpx.Response:
        if "/text-to-speech/" not in request.url.path:
            return httpx.Response(404)
        call = (request.headers["xi-api-key"], request.url.path.split("/")[3])
        seen.append((*call, json.loads(request.content)["model_id"]))
        status, body = answers.get(call, (200, AUDIO))
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handle)


@pytest.mark.parametrize("backups", [None, "", " , "])
def test_with_no_backup_keys_a_spent_quota_calls_only_the_main_key_as_before(
    tmp_path, monkeypatch, backups
):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    if backups is None:
        monkeypatch.delenv("ELEVENLABS_API_KEY_FALLBACKS", raising=False)
    else:
        monkeypatch.setenv("ELEVENLABS_API_KEY_FALLBACKS", backups)
    seen = []
    with client_for(tmp_path, keyed({(KEY, CONNOR): (401, QUOTA)}, seen), GOAL) as client:
        assert client.get("/lines/g1/audio").status_code == 503
        assert client.get("/stats").json()["voice"]["last_error"] == "quota_exceeded"
    v3 = (KEY, CONNOR, "eleven_v3")
    assert seen == [v3, v3, (KEY, CONNOR, "eleven_flash_v2_5")]


def test_a_spent_quota_moves_to_the_backup_keys_and_a_free_plan_one_speaks_as_george(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("ELEVENLABS_API_KEY_FALLBACKS", f"{BACKUP}, {BACKUP2}")
    caplog.set_level(logging.DEBUG)
    answers = {
        (KEY, CONNOR): (401, QUOTA),
        (BACKUP, CONNOR): (402, PAID),
        (BACKUP, GEORGE): (401, QUOTA),  # the first backup is spent too
        (BACKUP2, CONNOR): (402, PAID),
    }
    seen = []
    with client_for(tmp_path, keyed(answers, seen), GOAL) as client:
        resp = client.get("/lines/g1/audio")
        stats = client.get("/stats").text
    assert resp.status_code == 200 and resp.content == AUDIO
    assert seen == [
        (KEY, CONNOR, "eleven_v3"),
        (BACKUP, CONNOR, "eleven_v3"),
        (BACKUP, GEORGE, "eleven_v3"),
        (BACKUP2, CONNOR, "eleven_v3"),
        (BACKUP2, GEORGE, "eleven_v3"),
    ]
    assert '"provider":"elevenlabs"' in stats
    for secret in (KEY, BACKUP, BACKUP2):
        assert secret not in stats and secret not in caplog.text


def test_only_a_backup_key_retries_a_402_as_george(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setenv("ELEVENLABS_API_KEY_FALLBACKS", BACKUP)
    seen = []
    with client_for(tmp_path, keyed({(KEY, CONNOR): (402, PAID)}, seen), GOAL) as client:
        assert client.get("/lines/g1/audio").status_code == 503
    assert {k for k, *_ in seen} == {KEY} and GEORGE not in {v for _, v, _ in seen}


def test_stats_show_the_characters_left_read_at_most_every_five_minutes(
    tmp_path, monkeypatch, caplog
):
    from core import voice

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    caplog.set_level(logging.DEBUG)
    reads, answer = (
        [],
        [httpx.Response(200, json={"character_limit": 100_000, "character_count": 72_500})],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == voice.METER_URL and request.headers["xi-api-key"] == KEY
        reads.append(request)
        return answer[0]

    now = [1000.0]
    monkeypatch.setattr(voice.time, "monotonic", lambda: now[0])
    with client_for(tmp_path, httpx.MockTransport(handle)) as client:
        assert client.get("/stats").json()["voice"]["characters_left"] == 27_500
        answer[0] = httpx.Response(500)
        assert client.get("/stats").json()["voice"]["characters_left"] == 27_500  # cached
        assert len(reads) == 1
        now[0] += voice.METER_TTL_S
        body = client.get("/stats").text
    assert '"characters_left":null' in body and len(reads) == 2  # unreadable: null, never an error
    assert KEY not in body and KEY not in caplog.text


def test_a_429_opens_the_breaker_so_queued_lines_skip_to_subtitles(monkeypatch):
    import asyncio

    from core import voice
    from core.voice import VOICES, Speaker

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.setattr(voice, "BREAKER_S", 0.3)
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429 if len(seen) == 1 else 200, content=AUDIO)

    speaker = Speaker(httpx.MockTransport(handle))

    def line(i):
        return {"line_id": f"l{i}", "sport": "football", "text": "Goal!"}

    async def run():
        first = await speaker.audio(line(0), VOICES[1])  # 429: no v3 retry, no flash
        queued = await speaker.audio(line(1), VOICES[1])
        await asyncio.sleep(0.35)
        return first, queued, len(seen), await speaker.audio(line(2), VOICES[1])

    assert asyncio.run(run()) == (None, None, 1, (AUDIO, "eleven_v3"))


def test_a_goal_is_more_intense_than_a_pass_and_the_pair_is_voiced_to_match(monkeypatch):
    import asyncio
    import time

    from core.insight import stat_moment
    from core.voice import Speaker, analyst_voice, intensity

    goal = {"type": "Shot", "outcome": "Goal", "detail": {}, "score": {}}
    routine = {"type": "Pass", "detail": {}, "score": {}}
    assert (intensity(goal), intensity(routine)) == ("high", "calm")
    said_as = {"kind": "form", "detail": "x", "heard": "Goal!"}
    assert stat_moment(goal, said_as, False)["detail"]["intensity"] == "high"

    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((body["text"], body.get("voice_settings")))
        return httpx.Response(200, content=AUDIO)

    speaker = Speaker(httpx.MockTransport(handle))

    async def run(moment, line_id):
        line = {"line_id": line_id, "sport": "football", "speaker": "analyst", "text": "Two."}
        speaker.prepare(line, stat_moment(moment, said_as, False), time.monotonic() + 30)
        await speaker.audio(line, analyst_voice("football"))

    asyncio.run(run(goal, "a"))
    asyncio.run(run(routine, "b"))
    assert seen == [
        ("[excited] Two.", {"stability": 0.0}),
        ("[warmly] Two.", {"stability": 0.5}),
    ]
