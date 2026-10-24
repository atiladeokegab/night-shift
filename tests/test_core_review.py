"""The review queue (#171): stored lead lines the number check flags, fixed by the producer."""

import pytest
from fastapi.testclient import TestClient

from agent import commentator
from core import insight, review
from core.app import Deps, create_app
from core.stats import stats
from core.store import Store
from data.matches import list_matches, load_moments

KOBE = "0020500591"  # idx 4: Bryant's three for 41 points, Lakers 65, Raptors 75
SAID = "Kobe Bryant from deep, three points! Lakers trail"
WRONG = f"{SAID} fifty-eight to seventy-five, Bryant with forty-one."
RIGHT = f"{SAID} sixty-five to seventy-five, Bryant with forty-one."
WORSE = f"{SAID} fifty-nine to seventy-five, Bryant with forty-one."
UNSAID = f"{SAID} sixty-five to seventy-five."  # flagged only for leaving out his 41
CRICKET = "1298150"  # idx 11: Iftikhar's six, his third in four balls only by the moments before it
SIXES = "Another six! Iftikhar Ahmed, three sixes in four balls! Pakistan 88 for 2."
HEARD = "Bryant has only a 16% chance from there."  # the analyst, after idx 4
REPLY = {"match_id": KOBE, "after_idx": 4, "heard": HEARD}  # what the lead answered


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
        line("six", SIXES, speaker="lead", match_id=CRICKET, moment_idx=11),
        line("reply", "Sixteen percent, and he hits it anyway!", speaker="lead", reply=REPLY),
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


def test_a_reply_to_the_analyst_is_checked_against_what_the_analyst_said(tmp_path):
    store = Store(tmp_path)
    for ln in (
        line("said", "Sixteen percent, and he hits it anyway!", speaker="lead", reply=REPLY),
        line("unsaid", "Thirty-three percent, and he hits it anyway!", speaker="lead", reply=REPLY),
    ):
        store.append("lines", ln)
    deps = Deps(list_matches, load_moments, lambda m, h: None)
    queued = review.queue(store, deps)
    assert [q["line_id"] for q in queued] == ["unsaid"]
    assert queued[0]["wrong"] == ["33 is not in the moment"]
    assert queued[0]["play"] == f"The lead answers the analyst, who just said: {HEARD}"


def test_a_line_said_before_todays_check_is_marked_and_left_out_of_the_autonomy_count(tmp_path):
    store = Store(tmp_path)
    for ln in (
        line("old", WRONG, speaker="lead"),  # said before the check: only today's check fails it
        line("ok", RIGHT, speaker="lead", checked=True),
        line("live", RIGHT, speaker="lead", checked=True, fallback=True, tried=WORSE,
             wrong=["59 is not in the moment"]),  # the retry failed as it was said
    ):
        store.append("lines", ln)
    queued = review.queue(store, Deps(list_matches, load_moments, lambda m, h: None))
    assert [(q["line_id"], q["text"], q["later_check"]) for q in queued] == [
        ("live", WORSE, False),
        ("old", WRONG, True),
    ]
    assert queued[1]["wrong"] == ["58 is not in the moment"]  # the checker's reason, today
    auto = stats(store)["autonomy"]
    assert (auto["called"], auto["first_time"], auto["to_human"]) == (2, 1, 1)


def test_a_second_read_checks_only_the_lines_stored_since_and_a_fix_still_clears(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(review, "_checked", {})
    checked, real = [], insight.wrong_numbers
    monkeypatch.setattr(insight, "wrong_numbers", lambda t, *a: checked.append(t) or real(t, *a))
    store, deps = Store(tmp_path), Deps(list_matches, load_moments, lambda m, h: None)
    store.append("lines", line("old", WRONG, speaker="lead"))
    assert [q["line_id"] for q in review.queue(store, deps)] == ["old"]
    store.append("lines", line("new", WORSE, speaker="lead"))
    assert [q["line_id"] for q in review.queue(store, deps)] == ["new", "old"]
    assert checked == [WRONG, WORSE]  # each line checked once
    store.append("fixes", {"line_id": "old", "corrected_text": RIGHT})
    assert [q["line_id"] for q in review.queue(store, deps)] == ["new"]
