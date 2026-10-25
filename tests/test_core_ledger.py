"""The correction ledger: every Score check example sent and every auto-fix, each naming the Mubit
session and request it went in, built from the store's own records."""

import pytest
from fastapi.testclient import TestClient

from core import ledger
from core.app import Deps, create_app
from core.store import Store
from data.matches import list_matches, load_moments
from eval.linecheck import example_id
from eval.seed_scorecheck import send

KOBE = "0020500591"  # idx 4: Bryant's three for 41 points, Lakers 65, Raptors 75
WRONG = "Kobe Bryant from deep, three points! Lakers trail fifty-eight to seventy-five."
RIGHT = "Kobe Bryant from deep, three points! Lakers trail sixty-five to seventy-five."
SCORE = "Los Angeles Lakers 65, Toronto Raptors 75"


def line(line_id, text, **more):
    return {"line_id": line_id, "match_id": KOBE, "moment_idx": 4, "text": text, **more}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_cache", {})  # a store's id can be reused by the next test's
    store = Store(tmp_path)
    for ln in (line("w", WRONG, speaker="lead"), line("r", RIGHT, speaker="lead", retried=True)):
        store.append("lines", ln)
    at = "2026-10-24T20:0{}:00+00:00"
    for row in (
        # seeded before the ledger: only the example id names its line
        {
            "id": example_id(KOBE, 4, RIGHT),
            "kind": "matched",
            "gold": "ok",
            "mubit_request_id": "sc-1",
            "source": "seed",
            "created_at": at.format(1),
        },
        # a producer's fix: its line id
        {
            "id": example_id(KOBE, 4, WRONG),
            "kind": "corrected",
            "gold": "wrong",
            "mubit_request_id": "sc-2",
            "line_id": "w",
            "source": "fix",
            "created_at": at.format(3),
        },
        # a planted line no stored line says: what it can't name stays empty
        {
            "id": "planted1",
            "kind": "corrected",
            "gold": "wrong",
            "mubit_request_id": "sc-3",
            "source": "seed",
            "created_at": at.format(0),
        },
    ):
        store.append("scorecheck_examples", row)
    store.append(
        "auto_fixes",
        {
            "line_id": "w",
            "corrected_text": RIGHT,
            "reason": "auto: number check",
            "auto": True,
            "correction": "Producer correction: number check: 58 is not in the moment\n...",
            "mubit_request_id": "cm-1",
            "recorded": True,
            "created_at": at.format(2),
        },
    )
    deps = Deps(list_matches, load_moments, lambda m, h: None)
    with TestClient(create_app(store=store, deps=deps)) as c:
        c.store = store
        yield c


def test_ledger_lists_every_correction_newest_first_with_its_mubit_session_and_request(client):
    got = client.get("/ledger").json()
    assert got["sent"] == 3  # examples sent to Score check; an auto-fix goes to the commentator
    rows = got["rows"]
    assert [r["request_id"] for r in rows] == ["sc-2", "cm-1", "sc-1", "sc-3"]
    fix, auto, seed, planted = rows
    assert fix["source"] == "human" and fix["task"] == "Score check"
    assert fix["session"] == f"score-check-{KOBE}-4" and fix["text"] == WRONG
    assert fix["score"] == SCORE and fix["wrong"] == ["58 is not in the moment"]
    assert auto["source"] == "auto-fixed" and auto["task"] == "Commentator"
    assert auto["session"] == f"match-basketball-{KOBE}" and auto["fixed"] == RIGHT
    assert (
        auto["idx"] == 4 and auto["score"] == SCORE and auto["wrong"] == ["58 is not in the moment"]
    )
    assert seed["source"] == "answer key" and seed["text"] == RIGHT and seed["wrong"] == []
    assert seed["session"] == f"score-check-{KOBE}-4" and seed["idx"] == 4
    assert planted["text"] is None and planted["session"] is None and planted["score"] is None
    assert all(r["link"] is None for r in rows)  # no console URL known yet: no link


def test_a_console_url_links_each_row_to_its_session_and_request(client, monkeypatch):
    monkeypatch.setattr(
        ledger, "MUBIT_REQUESTS_URL", "https://console.example/r?s={session}&id={request}"
    )
    fix = client.get("/ledger").json()["rows"][0]
    assert fix["link"] == f"https://console.example/r?s=score-check-{KOBE}-4&id=sc-2"


def test_a_sent_example_names_its_line_so_the_ledger_needs_no_lookup():
    class Fake:
        def call(self, req):
            return {"request_id": "x", "content": [{"type": "text", "text": '{"score":"wrong"}'}]}

    ex = {"id": "e", "match_id": KOBE, "idx": 4, "text": WRONG, "gold": "wrong"}
    sent = send(ex, Fake())
    assert (sent["match_id"], sent["idx"], sent["text"]) == (KOBE, 4, WRONG)


def test_a_second_call_within_the_window_does_not_rebuild(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ledger.time, "monotonic", lambda: now[0])
    built = []
    build = ledger.ledger
    monkeypatch.setattr(ledger, "ledger", lambda *a: built.append(1) or build(*a))
    assert client.get("/ledger").json()["sent"] == 3
    client.store.append("scorecheck_examples", {"id": "new", "kind": "matched", "source": "seed"})
    now[0] += ledger.TTL_S - 1
    assert client.get("/ledger").json()["sent"] == 3 and len(built) == 1  # served from the cache
    now[0] += 1
    assert client.get("/ledger").json()["sent"] == 4 and len(built) == 2  # the window is over


def test_only_the_newest_rows_are_returned_with_every_example_counted(client, monkeypatch):
    monkeypatch.setattr(ledger, "SHOWN", 2)
    got = client.get("/ledger").json()
    assert got["sent"] == 3 and [r["request_id"] for r in got["rows"]] == ["sc-2", "cm-1"]


def test_a_match_off_the_picker_keeps_its_title_and_planted_rows_stay_unnamed(client):
    rows = ledger.ledger(client.store, Deps(lambda: [], load_moments, lambda m, h: None))["rows"]
    named = {r["request_id"]: r["match"] for r in rows}
    assert named["sc-2"] == "Los Angeles Lakers v Toronto Raptors, NBA Regular season"
    assert named["sc-3"] is None
