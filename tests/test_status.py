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


def upto(idx):
    return [m for m in load_moments(JORDAN) if m["idx"] <= idx]


def line(m, history):
    return {
        "line_id": f"l{m['idx']}",
        "match_id": JORDAN,
        "moment_idx": m["idx"],
        "text": "Bucket!",
    }


def test_after_a_jump_the_status_comes_from_the_moment_on_screen(tmp_path):
    provider, store = FakeProvider(), Store(tmp_path)
    deps = Deps(lambda: [], load_moments, line, status=partial(st.status, provider=provider))
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
    assert said["text"] == "quarter 4, 00:37. Utah Jazz 86, Chicago Bulls 85. Utah Jazz lead 86-85."
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
    assert said["text"] == "Quarter 4, 00:37. Utah Jazz 86, Chicago Bulls 85. Utah Jazz lead 86-85."
    assert said["mubit_request_ids"] == []


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
