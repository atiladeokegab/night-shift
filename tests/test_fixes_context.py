"""A producer's fix applies to the next lines straight away: the match's stored fixes go in the
user message of each later line's request, never the system prompt, tools or model."""

import functools
import json

from fastapi.testclient import TestClient

from agent import commentator
from agent.commentator import FakeProvider, build_request, match_fixes, render_message
from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments, match_header

JAZZ, KOBE = "0049700088", "0020500591"
TRIED = "Jordan with the driving layup! Chicago Bulls take the lead, 85-86!"
FIXED = "Michael Jordan with the driving layup, forty-three for him! Utah still lead."


def jordan_fix(tmp_path) -> Store:
    """The Jordan fix at moment 30: a fallback line, its failed try and the check's reason."""
    store = Store(tmp_path)
    store.append(
        "lines",
        {
            "line_id": "j30",
            "match_id": JAZZ,
            "moment_idx": 30,
            "text": "Michael Jordan with the driving layup. Utah Jazz lead eighty-six, eighty-five",
            "tried": TRIED,
            "wrong": ["Chicago Bulls do not lead"],
            "fallback": True,
        },
    )
    store.append("fixes", {"line_id": "j30", "corrected_text": FIXED, "reason": "Wrong score"})
    return store


def request_at(match_id, idx, fixes):
    moments = load_moments(match_id)
    return build_request(match_header(match_id), moments[: idx + 1], fixes)


def test_a_fix_is_in_the_user_message_of_a_later_line_of_its_match_only(tmp_path):
    store = jordan_fix(tmp_path)
    later = request_at(JAZZ, 34, match_fixes(store, JAZZ))["messages"][0]["content"]
    assert later.endswith(
        "\nProducer fixes earlier in this match, to follow from now on:\n"
        f"- quarter 4, 00:37: you said {json.dumps(TRIED)} (Chicago Bulls do not lead);"
        f" the producer's line: {json.dumps(FIXED)}"
    )
    assert match_fixes(store, KOBE) == []  # another match's request never sees it
    assert (
        "Producer fixes"
        not in request_at(KOBE, 34, match_fixes(store, KOBE))["messages"][0]["content"]
    )


def test_no_fixes_leave_the_request_byte_identical(tmp_path):
    store = jordan_fix(tmp_path)
    moments = load_moments(JAZZ)
    for idx, fixes in ((34, []), (29, match_fixes(store, JAZZ))):  # 29: the fix's moment is later
        request = request_at(JAZZ, idx, fixes)
        assert json.dumps(request) == json.dumps(request_at(JAZZ, idx, ()))
        assert request["messages"] == [
            {"role": "user", "content": render_message(match_header(JAZZ), moments[: idx + 1])}
        ]


def test_the_system_prompt_tools_and_model_are_the_same_with_and_without_fixes(tmp_path):
    fixes = match_fixes(jordan_fix(tmp_path), JAZZ)
    with_, without = request_at(JAZZ, 34, fixes), request_at(JAZZ, 34, [])
    assert with_["system"] == without["system"] == commentator.SYSTEM
    assert {k: v for k, v in with_.items() if k != "messages"} == {
        k: v for k, v in without.items() if k != "messages"
    }
    assert with_["messages"][0]["content"].startswith(without["messages"][0]["content"] + "\n")


def test_at_most_the_last_five_fixes_and_the_newest_per_line(tmp_path):
    store = Store(tmp_path)
    for i in range(7):
        store.append("lines", {"line_id": f"l{i}", "match_id": JAZZ, "moment_idx": i, "text": "x"})
        store.append("fixes", {"line_id": f"l{i}", "corrected_text": f"fix {i}"})
    store.append("fixes", {"line_id": "l0", "corrected_text": "fix 0 again"})
    fixes = match_fixes(store, JAZZ)
    assert [f["fixed"] for f in fixes] == [f"fix {i}" for i in range(1, 7)] + ["fix 0 again"]
    said = request_at(JAZZ, 34, fixes)["messages"][0]["content"].split("follow from now on:\n")[1]
    assert [ln.rsplit(": ", 1)[1] for ln in said.splitlines()] == [
        json.dumps(f"fix {i}") for i in (3, 4, 5, 6)
    ] + [json.dumps("fix 0 again")]


def test_a_replay_sends_a_stored_fix_with_every_later_line(tmp_path):
    store, fake = jordan_fix(tmp_path), FakeProvider()
    calls = functools.partial(commentator.commentate, provider=fake)
    deps = Deps(list_matches, load_moments, calls, fixes=True)
    with TestClient(create_app(store=store, deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": JAZZ, "speed": 1e6}).json()["replay_id"]
        read_stream(client, rid)
    sent = {}
    for r in fake.requests:
        m = r["messages"][0]["content"]
        clock = next(ln for ln in m.splitlines() if ln.startswith("Moment: "))
        sent[clock] = "Producer fixes earlier in this match" in m
    moments = load_moments(JAZZ)
    before = [m for m in moments if m["idx"] < 30]
    after = [m for m in moments if m["idx"] > 30]
    at = {f"Moment: {commentator._period(m)}, {m['clock']}": m for m in moments}
    assert any(sent[k] for k, m in at.items() if m in after and k in sent)
    assert not any(sent[k] for k, m in at.items() if m in before and k in sent)
    assert all(r["system"] == commentator.SYSTEM for r in fake.requests)
