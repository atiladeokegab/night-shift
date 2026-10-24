"""'Where are we?' (#186): its own Mubit task, asked by button, key or words, from the moment on
screen, and checked so a wrong score or leader is never spoken."""

from functools import partial

import pytest
from fastapi.testclient import TestClient

from agent import status as st
from agent.commentator import SYSTEM, TOOLS, FakeProvider
from core.app import Deps, create_app, wants_status
from core.smoke import read_stream
from core.store import Store
from data.matches import load_moments, match_header

JORDAN = "0049700088"  # Game 6, 1998: the Jazz lead 86-85 after Jordan's layup at idx 30
KOBE, CRICKET, FINAL = "0020500591", "1298150", "3869685"


class Says:
    """A provider that says the same line every call."""

    def __init__(self, text):
        self.text, self.requests = text, []

    def call(self, request):
        self.requests.append(request)
        n = len(self.requests)
        return {
            "content": [{"type": "text", "text": self.text}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "request_id": f"says-{n}",
            "first_word_ms": 1.0,
        }


class OffAir:
    def call(self, request):
        raise RuntimeError("402 Payment Required")


def upto(idx, match_id=JORDAN):
    return [m for m in load_moments(match_id) if m["idx"] <= idx]


def sent(match_id, idx):
    m = upto(idx, match_id)[-1]
    return st.build_request(match_header(match_id), m)["messages"][0]["content"]


def line(m, history):
    return {
        "line_id": f"l{m['idx']}",
        "match_id": JORDAN,
        "moment_idx": m["idx"],
        "text": "Bucket!",
    }


def test_after_a_jump_the_status_comes_from_the_moment_on_screen(tmp_path):
    provider, store = FakeProvider(), Store(tmp_path)

    def ask(*_):
        raise AssertionError("a status phrase never reaches the Ask prompt")

    deps = Deps(
        lambda: [], load_moments, line, ask=ask, status=partial(st.status, provider=provider)
    )
    client = TestClient(create_app(store=store, deps=deps))
    with client:
        body = {"match_id": JORDAN, "speed": 1e6, "start_idx": 29}
        rid = client.post("/replays", json=body).json()["replay_id"]
        read_stream(client, rid)  # the whole match from the jump on has been sent
        resp = client.post(
            f"/replays/{rid}/ask", json={"question": "Where are we?", "moment_idx": 30}
        )
    said = resp.json()
    assert resp.status_code == 200 and said["status"] and said["moment_idx"] == 30
    assert said["text"] == "Fourth quarter, 0:37 left. Utah Jazz lead 86-85."
    assert [r["system"] for r in provider.requests] == [st.SYSTEM]  # its own task, not Ask's
    sent = provider.requests[-1]["messages"][0]["content"]
    assert "Last event: Field goal, 2 points (Chicago Bulls" in sent and "00:18" not in sent
    assert store.all("answers") == [said]


def test_the_status_is_its_own_task_and_the_lines_task_is_untouched():
    request = st.build_request(match_header(JORDAN), upto(30)[-1])
    assert request["system"] == st.SYSTEM != SYSTEM and "tools" not in request
    assert TOOLS and request["model"] == "claude-haiku-4-5"


def test_a_wrong_leader_is_rejected_and_the_data_speaks():
    wrong = Says(
        "Thirty-seven seconds left. Chicago Bulls take the lead, eighty-five to eighty-six!"
    )
    said = st.status(upto(30), provider=wrong)
    assert len(wrong.requests) == 2  # tried again once, then the line from the data
    assert said["text"] == st.fallback_text(match_header(JORDAN), upto(30)[-1])
    assert "Utah Jazz lead 86-85" in said["text"]


def test_a_right_status_is_spoken_as_said():
    right = Says("Thirty-seven seconds left. The Jazz lead eighty-six to eighty-five. Bulls ball.")
    said = st.status(upto(30), provider=right)
    assert said["text"] == right.text and len(right.requests) == 1
    assert said["mubit_request_ids"] == ["says-1"]


def test_off_air_the_status_still_comes_from_the_data():
    said = st.status(upto(30), provider=OffAir())
    assert said["text"] == "Fourth quarter, 0:37 left. Utah Jazz lead 86-85."
    assert said["mubit_request_ids"] == []


# The keyed probe on #194's first prompt: each of these was said wrong by the real model.
def test_the_time_says_what_the_clock_means():
    assert "Moment: First quarter, 0:30 left\n" in sent(JORDAN, 8)  # said "thirty seconds gone"
    assert "Moment: Second half, 96 minutes played\n" in sent(
        FINAL, 34
    )  # "... thirty-seven seconds"
    assert "Moment: Penalty shootout\n" in sent(FINAL, 67)


def test_a_cricket_wicket_names_each_role():
    # said "Hardik Pandya just caught Shadab Khan at SA Yadav"
    want = "HH Pandya bowling to Shadab Khan; Shadab Khan is out, caught by SA Yadav"
    assert f"Last event: Wicket, caught (Pakistan batting; {want})" in sent(CRICKET, 14)
    assert "non_striker" not in sent(CRICKET, 14)


def test_the_fallback_says_the_time_and_the_lead_once():
    m = upto(13, KOBE)[-1]
    assert st.fallback_text(match_header(KOBE), m) == (
        "Fourth quarter, 6:32 left. Los Angeles Lakers lead 102-93."
    )
    cricket = upto(14, CRICKET)[-1]
    assert (
        st.fallback_text(match_header(CRICKET), cricket)
        == "Innings 1, over 13.2. Pakistan 96 for 4."
    )


def test_a_status_without_the_score_is_tried_again_then_the_data_speaks():
    # Kobe idx 6, 78-73 to Toronto: the probe's line left the score out
    said = "Four forty-seven left in the third quarter. Kobe Bryant just hit a three-pointer."
    missing = Says(said)
    out = st.status(upto(6, KOBE), provider=missing)
    assert len(missing.requests) == 2
    assert out["text"] == "Third quarter, 4:47 left. Toronto Raptors lead 78-73."
    scored = Says(
        "Four forty-seven left in the third. Raptors lead seventy-eight to seventy-three."
    )
    assert st.status(upto(6, KOBE), provider=scored)["text"] == scored.text


def test_one_nil_is_a_score_and_a_milestone_is_not_asked_for():
    spurs = upto(11, "3754092")[-1]  # Chelsea 0, Tottenham 1
    assert st.says_score("Thirty-four minutes gone. Tottenham lead one-nil.", spurs)
    assert not st.says_score("Thirty-four minutes gone. Tottenham lead.", spurs)
    # Kobe idx 13 has a 61-point milestone: a status line needn't say it (the probe fell back)
    line = "Six thirty-two left in the fourth. Lakers one hundred and two, Raptors ninety-three."
    said = Says(line)
    assert st.status(upto(13, KOBE), provider=said)["text"] == line and len(said.requests) == 1


def test_f1_and_a_first_innings_send_the_real_leader():
    assert "Who leads: Esteban Ocon leads\n" in sent("9636", 7)  # P1 on lap 29
    assert "Who leads: no one yet, Pakistan batting first\n" in sent(CRICKET, 14)
    assert "Who leads: India need 150 runs from the last 100 balls\n" in sent(CRICKET, 28)


def test_a_status_needn_t_say_how_the_last_shot_ended():
    # the final's idx 45: Lautaro off target at 105:41; the status is the state, not the shot
    line = "A hundred and five minutes played in extra time. Argentina two, France two, level."
    said = Says(line)
    assert st.status(upto(45, FINAL), provider=said)["text"] == line and len(said.requests) == 1
    # a save called on a shot off target is still wrong
    saved = Says("Extra time. Argentina two, France two. Lloris saves from Lautaro.")
    assert st.status(upto(45, FINAL), provider=saved)["text"] != saved.text


def test_the_shootout_fallback_says_the_match_score_too():
    m = upto(67, FINAL)[-1]
    assert st.fallback_text(match_header(FINAL), m) == (
        "Penalty shootout, 3-3 after extra time. Argentina lead the shootout 4-2."
    )


def test_offline_a_tie_is_said_once():
    out = st.status(upto(19), provider=FakeProvider())  # Jordan's Game 6, 70-70 at 8:05
    assert out["text"] == "Fourth quarter, 8:05 left. Level at 70-70."
    assert st.fallback_text(match_header(JORDAN), upto(19)[-1]) == out["text"]


@pytest.mark.parametrize(
    "question,yes",
    [
        ("Where are we?", True),
        ("where are we at", True),
        ("What's the score?", True),
        ("what is the score now", True),
        ("So, where are we?", True),
        ("What’s the score?", True),  # a phone keyboard's apostrophe
        ("Where are we going to score from?", False),
        ("What's the score in the other game?", False),
    ],
)
def test_the_status_phrases(question, yes):
    assert wants_status(question) is yes
