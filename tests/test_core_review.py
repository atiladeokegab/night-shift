"""The review queue (#171): stored lead lines the number check flags, fixed by the producer."""

import pytest
from fastapi.testclient import TestClient

from agent import commentator
from core.app import Deps, create_app
from core.store import Store
from data.matches import list_matches, load_moments

KOBE = "0020500591"  # idx 4: Bryant's three for 41 points, Lakers 65, Raptors 75
SAID = "Kobe Bryant from deep, three points! Lakers trail"
WRONG = f"{SAID} fifty-eight to seventy-five, Bryant with forty-one."
RIGHT = f"{SAID} sixty-five to seventy-five, Bryant with forty-one."
UNSAID = f"{SAID} sixty-five to seventy-five."  # flagged only for leaving out his 41


def line(line_id, text, **more):
    return {"line_id": line_id, "match_id": KOBE, "moment_idx": 4, "text": text, **more}


@pytest.fixture
def client(tmp_path, monkeypatch):
    class Owner(commentator.FakeProvider):  # Mubit on the owner's key: records for training
        def __init__(self, key, record=True, fallback=None):
            super().__init__()
            self.record = record

    monkeypatch.setattr(commentator, "MubitProvider", Owner)
    monkeypatch.setattr(commentator, "_trainer", None)
    monkeypatch.setenv("MUBIT_FALLBACK_KEY", "owner-key")
    store = Store(tmp_path)
    for ln in (
        line("w-old", WRONG, speaker="lead"),
        line("r", RIGHT, speaker="lead"),
        line("u", UNSAID),  # no speaker: stored before #130, the lead's
        line("a", WRONG, speaker="analyst"),
        line("w-new", WRONG, speaker="lead"),  # the same text again: one entry, the newest
    ):
        store.append("lines", ln)
    deps = Deps(list_matches, load_moments, lambda m, h: None, correct=commentator.correct)
    with TestClient(create_app(store=store, deps=deps)) as c:
        yield c


def test_review_lists_only_the_wrong_line_once_newest_first_with_what_is_wrong(client):
    queued = client.get("/review").json()
    assert [q["line_id"] for q in queued] == ["w-new"]
    q = queued[0]
    assert q["wrong"] == ["58 is not in the moment"] and q["text"] == WRONG
    assert q["match"] == "Los Angeles Lakers v Toronto Raptors, NBA Regular season"
    assert (q["moment_idx"], q["clock"], q["period"]) == (4, "06:22", 3)
    assert q["score"] == "Los Angeles Lakers 65, Toronto Raptors 75"
    assert q["play"].startswith("Bryant 26' 3PT Jump Shot")


def test_a_fix_from_review_empties_the_queue_and_counts_like_a_replays_fix(client):
    fixed = RIGHT
    resp = client.post("/lines/w-new/fix", json={"corrected_text": fixed, "reason": "Wrong score"})
    assert resp.status_code == 200 and resp.json()["recorded"] is True
    assert client.get("/review").json() == []  # its older copy, same text, goes with it
    stats = client.get("/stats").json()
    assert stats["fixes"] == 1 and stats["fixes_recorded"] == 1
