"""A producer's fix is heard on the next replay; a fix the data contradicts is refused (#232)."""

import asyncio
import uuid

from fastapi.testclient import TestClient

from core import insight
from core.app import Deps, create_app
from core.replay import Replay, run_replay
from core.stats import stats
from core.store import Store
from data.matches import list_matches, load_moments, match_header

KOBE = "0020500591"  # idx 4: Bryant's three for 41 points, Lakers 65, Raptors 75
SAID = "Kobe Bryant from deep, three points! Lakers trail"
WRONG = f"{SAID} fifty-eight to seventy-five, Bryant with forty-one."
RIGHT = f"{SAID} sixty-five to seventy-five, Bryant with forty-one."
MODEL = "From the model."  # a milestone moment's retry and fallback call it twice


def stored(store, line_id, text, idx=4):
    line = {"line_id": line_id, "match_id": KOBE, "moment_idx": idx, "text": text}
    return store.append("lines", {**line, "speaker": "lead"})


def replay(store, n=6):
    called = []

    def commentate(m, history):
        called.append(m["idx"])
        line_id = uuid.uuid4().hex
        return {"line_id": line_id, "match_id": KOBE, "moment_idx": m["idx"], "text": MODEL}

    r = Replay(KOBE, 1e9)
    asyncio.run(run_replay(r, load_moments(KOBE)[:n], commentate, store))
    said = {e["data"]["moment_idx"]: e["data"] for e in r.events if e["event"] == "line"}
    return said, sorted(set(called))


def test_the_next_replay_speaks_the_fix_and_never_calls_the_model_for_that_moment(tmp_path):
    store = Store(tmp_path)
    stored(store, "w", WRONG)
    store.append("fixes", {"line_id": "w", "corrected_text": WRONG, "created_at": "1"})
    store.append("fixes", {"line_id": "w", "corrected_text": RIGHT, "created_at": "2"})  # newest
    said, called = replay(store)
    assert called == [0, 1, 2, 3, 5]  # every other moment is the model's, as before
    assert (said[4]["text"], said[4]["fixed"], said[4]["fix_id"]) == (RIGHT, True, "w")
    assert said[4] in store.all("lines")  # stored like any line said
    assert stats(store)["spoken_from_fix"] == 1


def test_a_fix_at_another_moment_leaves_this_one_to_the_model(tmp_path):
    store = Store(tmp_path)
    stored(store, "w", WRONG, idx=3)
    at_3 = insight.fallback_text(match_header(KOBE), load_moments(KOBE)[3])  # right at idx 3
    store.append("fixes", {"line_id": "w", "corrected_text": at_3})
    said, called = replay(store)
    assert said[3]["text"] == at_3 and said[3]["fixed"]
    assert called == [0, 1, 2, 4, 5] and "fixed" not in said[4]


def test_a_stored_fix_that_fails_todays_check_is_not_spoken(tmp_path):
    store = Store(tmp_path)
    stored(store, "w", WRONG)
    store.append("fixes", {"line_id": "w", "corrected_text": WRONG})  # stored before the check
    said, called = replay(store)
    assert called == [0, 1, 2, 3, 4, 5] and "fixed" not in said[4]


def test_a_fix_the_data_contradicts_or_over_200_characters_gets_422_and_stores_nothing(tmp_path):
    store = Store(tmp_path)
    stored(store, "w", WRONG)
    sent = []

    def correct(line, text, **more):
        sent.append(text)
        return {"mubit_request_id": "m", "reply_matched": True, "recorded": True}

    deps = Deps(list_matches, load_moments, lambda m, h: None, correct=correct)
    with TestClient(create_app(store=store, deps=deps)) as c:
        bad = c.post("/lines/w/fix", json={"corrected_text": WRONG, "reason": "Wrong score"})
        assert bad.status_code == 422
        assert bad.json()["detail"] == {"wrong": ["58 is not in the moment"]}
        long = c.post("/lines/w/fix", json={"corrected_text": RIGHT + " " + "x" * 200})
        assert long.status_code == 422
        assert store.all("fixes") == [] and sent == []  # never sent to Mubit for training
        assert c.post("/lines/w/fix", json={"corrected_text": RIGHT}).status_code == 200
        assert sent == [RIGHT]


def test_a_fix_needs_the_producer_token_once_the_deploy_sets_one(tmp_path, monkeypatch):
    store = Store(tmp_path)
    stored(store, "w", WRONG)
    sent = []

    def correct(line, text, **more):
        sent.append(text)
        return {"mubit_request_id": "m", "reply_matched": True, "recorded": True}

    deps = Deps(list_matches, load_moments, lambda m, h: None, correct=correct)
    body = {"corrected_text": RIGHT, "reason": "Wrong score"}
    with TestClient(create_app(store=store, deps=deps)) as c:
        monkeypatch.setenv("PRODUCER_TOKEN", "s3cret")
        assert c.post("/lines/w/fix", json=body).status_code == 401
        wrong = c.post("/lines/w/fix", json=body, headers={"X-Producer-Token": "guess"})
        assert wrong.status_code == 401
        assert store.all("fixes") == [] and sent == []  # nothing stored, nothing sent to Mubit
        right = c.post("/lines/w/fix", json=body, headers={"X-Producer-Token": "s3cret"})
        assert right.status_code == 200 and len(store.all("fixes")) == 1
        monkeypatch.delenv("PRODUCER_TOKEN")  # unset: local and tests, the check is off
        assert c.post("/lines/w/fix", json=body).status_code == 200


def test_a_cached_replay_says_the_stored_fix_line_so_its_audio_is_found(tmp_path):
    # prod: Brighton's cached replays made a new id for a fixed moment each time, never stored,
    # so /lines/{id}/audio was 404
    from core.guard import SayOnly

    store = Store(tmp_path)
    stored(store, "w", WRONG)
    store.append("fixes", {"line_id": "w", "corrected_text": RIGHT})
    first, _ = replay(store)  # makes and stores the fixed line
    again, _ = replay(SayOnly(store))  # a cached replay stores nothing
    assert again[4]["line_id"] == first[4]["line_id"]
    assert again[4]["line_id"] in {ln["line_id"] for ln in store.all("lines")}
