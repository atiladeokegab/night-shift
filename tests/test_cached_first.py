"""Cached first: a match's stored lines are said again with no model call, unless a producer's
fix is newer than them, and every line's ElevenLabs clip is saved once and served again."""

import httpx
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import GcsStore, Store
from core.voice import voice_of
from data.matches import list_matches, load_moments, video_map
from tests.test_core_store import FakeClient
from tests.test_guard import app, start, stored, texts
from tests.test_insight import CHELSEA
from tests.test_insight import replay as insight_replay


def test_a_match_with_stored_lines_replays_them_with_no_model_call(tmp_path):
    store = Store(tmp_path)
    stored(store)
    client, calls = app(store, {})
    with client:
        said = texts(client, start(client).json()["replay_id"])
    assert said == ["Stored 0", "Stored 1", "Stored 2"] and calls == []
    assert len(store.all("lines")) == 3  # said again, never stored again


def test_a_match_with_no_stored_lines_is_made_fresh(tmp_path):
    store = Store(tmp_path)
    client, calls = app(store, {})
    with client:
        said = texts(client, start(client).json()["replay_id"])
    assert said == ["New", "New", "New"] and calls == [0, 1, 2]


def test_a_fix_newer_than_the_match_lines_makes_them_fresh(tmp_path):
    store = Store(tmp_path)
    stored(store)
    fix = {"line_id": "old1", "match_id": "7", "moment_idx": 1, "corrected_text": "Fixed"}
    store.append("fixes", {**fix, "created_at": "2026-10-24T10:00:00+00:00"})
    client, calls = app(store, {})
    with client:
        texts(client, start(client).json()["replay_id"])
    assert calls == [0, 1, 2]  # made again, each call given the fix


def test_a_fix_older_than_the_match_lines_keeps_them_cached(tmp_path):
    store = Store(tmp_path)
    store.append(
        "fixes", {"line_id": "x", "match_id": "7", "created_at": "2026-10-24T08:00:00+00:00"}
    )
    stored(store)
    client, calls = app(store, {})
    with client:
        said = texts(client, start(client).json()["replay_id"])
    assert said == ["Stored 0", "Stored 1", "Stored 2"] and calls == []


def smoke(client, token=None):
    headers = {"x-producer-token": token} if token else {}
    body = {"match_id": "7", "speed": 1e6, "smoke": True}
    return texts(client, client.post("/replays", json=body, headers=headers).json()["replay_id"])


def test_the_deploy_smoke_with_the_producer_token_is_made_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCER_TOKEN", "secret")
    store = Store(tmp_path)
    stored(store)
    client, calls = app(store, {})
    with client:
        smoke(client, "secret")
    assert calls == [0, 1, 2]


def test_a_smoke_flag_without_the_producer_token_plays_the_stored_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCER_TOKEN", "secret")
    store = Store(tmp_path)
    stored(store)
    client, calls = app(store, {})
    with client:
        assert smoke(client) == ["Stored 0", "Stored 1", "Stored 2"]
    assert calls == []


def test_a_saved_clip_is_served_off_air_and_a_new_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    store, voiced = Store(tmp_path), []
    stored(store, model="claude-haiku-4-5", tokens_in=1000)  # $0.003 today: past the cap
    store.save_clip("old0", voice_of({})["id"], b"saved", "audio/mpeg")
    client, _ = app(store, {"DAILY_BUDGET_USD": "0.001"}, tts=tts_counting(voiced))
    with client:
        saved, new = client.get("/lines/old0/audio"), client.get("/lines/old1/audio")
    assert saved.status_code == 200 and saved.content == b"saved"
    assert new.status_code == 503 and voiced == []


def tts_counting(voiced):
    return httpx.MockTransport(
        lambda req: voiced.append(req) or httpx.Response(200, content=b"mp3")
    )


def test_a_cached_line_with_no_clip_makes_one_elevenlabs_call_and_saves_it(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    store, voiced = Store(tmp_path), []
    stored(store)
    client, _ = app(store, {}, tts=tts_counting(voiced))
    with client:
        texts(client, start(client).json()["replay_id"])
        first = client.get("/lines/old1/audio")
    restarted, _ = app(store, {}, tts=tts_counting(voiced))  # another instance: memory is gone
    with restarted:
        again = restarted.get("/lines/old1/audio")
    assert first.status_code == 200 and first.content == b"mp3"
    assert again.status_code == 200 and again.content == b"mp3"
    assert len(voiced) == 1  # made once, then served from the store
    assert [v["line_id"] for v in store.all("voice")] == ["old1"]  # its characters are counted
    assert store.all("voice")[0]["chars"] > 0


def test_a_saved_clip_is_served_with_no_elevenlabs_call(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    store, voiced = Store(tmp_path), []
    stored(store)
    client, _ = app(store, {}, tts=tts_counting(voiced))
    store.save_clip("old0", voice_of({})["id"], b"saved", "audio/mpeg")
    with client:
        events = read_stream(client, start(client).json()["replay_id"])
        audio = client.get("/lines/old0/audio")
    assert [d["line_id"] for n, d in events if n == "line"] == ["old0", "old1", "old2"]
    assert audio.status_code == 200 and audio.content == b"saved"
    assert audio.headers["content-type"] == "audio/mpeg"
    assert voiced == [] and store.all("voice") == []


def test_a_gcs_store_keeps_a_clip_and_its_type(tmp_path):
    store = GcsStore("gs://b/prefix", client=FakeClient())
    assert store.clip("l1", "v1") is None
    store.save_clip("l1", "v1", b"\x00mp3", "audio/mpeg")
    assert store.clip("l1", "v1") == (b"\x00mp3", "audio/mpeg")
    assert Store(tmp_path).clip("l1", "v1") is None


def test_the_newest_stored_line_for_a_moment_is_the_one_said_again(tmp_path):
    store = Store(tmp_path)
    stored(store)
    store.append(
        "lines",
        {"line_id": "later0", "match_id": "7", "moment_idx": 0, "speaker": "lead", "text": "Later"},
    )
    client, calls = app(store, {})
    with client:
        said = texts(client, start(client).json()["replay_id"])
    assert said == ["Later", "Stored 1", "Stored 2"] and calls == []


def fresh(client, token=None):
    headers = {"x-producer-token": token} if token else {}
    body = {"match_id": "7", "speed": 1e6, "fresh": True}
    return texts(client, client.post("/replays", json=body, headers=headers).json()["replay_id"])


def test_fresh_with_the_producer_token_makes_a_stored_match_again(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCER_TOKEN", "secret")
    store = Store(tmp_path)
    stored(store)
    client, calls = app(store, {})
    with client:
        assert fresh(client, "secret") == ["New", "New", "New"]
    assert calls == [0, 1, 2]


def test_fresh_without_a_valid_producer_token_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCER_TOKEN", "secret")
    store = Store(tmp_path)
    stored(store)
    client, calls = app(store, {})
    with client:
        assert fresh(client) == ["Stored 0", "Stored 1", "Stored 2"]
        assert fresh(client, "wrong") == ["Stored 0", "Stored 1", "Stored 2"]
    assert calls == []


def test_a_cached_replay_says_the_analysts_stored_lines_with_their_clips(tmp_path, monkeypatch):
    """The two-hander: the analyst's lines and the lead's comebacks between moments are said
    again from the store, with no model call, and each is voiced once, then from its clip."""
    first, _ = insight_replay(CHELSEA, Store(tmp_path))  # a fresh replay stores both voices
    analyst = [ln for ln in first if ln.get("speaker") == "analyst"]
    assert analyst

    def no_model(moment, history, **kw):
        raise AssertionError("a cached replay must not call the model")

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    voiced = []
    deps = Deps(list_matches, load_moments, no_model, video_map)
    store = Store(tmp_path)
    client = TestClient(create_app(store, deps, tts_transport=tts_counting(voiced)))
    with client:
        rid = client.post("/replays", json={"match_id": CHELSEA, "speed": 1e9}).json()
        again = [d for n, d in read_stream(client, rid["replay_id"]) if n == "line"]
        one = analyst[0]["line_id"]
        audio = [client.get(f"/lines/{one}/audio") for _ in range(2)]
    assert [ln["line_id"] for ln in again] == [ln["line_id"] for ln in first]
    assert [a.status_code for a in audio] == [200, 200] and len(voiced) == 1
    assert len(store.all("lines")) == len(first)  # nothing stored again
