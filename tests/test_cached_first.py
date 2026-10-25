"""Cached first: a match's stored lines are said again with no model call, unless a producer's
fix is newer than them, and every line's ElevenLabs clip is saved once and served again."""

import httpx

from core.smoke import read_stream
from core.store import GcsStore, Store
from core.voice import voice_of
from tests.test_core_store import FakeClient
from tests.test_guard import app, start, stored, texts


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


def test_the_deploy_smoke_is_always_made_fresh(tmp_path):
    store = Store(tmp_path)
    stored(store)
    client, calls = app(store, {})
    with client:
        rid = client.post("/replays", json={"match_id": "7", "speed": 1e6, "smoke": True})
        texts(client, rid.json()["replay_id"])
    assert calls == [0, 1, 2]


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
