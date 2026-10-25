"""A minute appearing elsewhere in the match is not evidence of the current clock."""

import pytest

from core import converse, insight
from data.matches import load_moments

MOMENTS = load_moments("3869685")
PAST = [m for m in MOMENTS if m["idx"] <= 41]  # 101:37, first half of extra time
WRONG = "One hundred and four minutes gone."
RIGHT = "One hundred and one minutes gone."


@pytest.mark.parametrize(
    "text",
    [
        WRONG,
        "104 minutes played.",
        "We're now one hundred and four minutes gone.",
        "It is 104 minutes elapsed.",
        "Level here. One hundred and four minutes gone.",
        "One minute gone.",
        "A minute played.",
    ],
)
def test_a_current_minute_is_checked_against_the_clock_not_other_numbers(text):
    assert insight.wrong_claims(text, PAST)


@pytest.mark.parametrize(
    "text",
    [
        RIGHT,
        "101 minutes played.",
        "We're now one hundred and one minutes gone.",
        "102 minutes gone.",  # the current minute, rather than completed minutes
        "After ninety minutes played, the score was level.",
        "At ninety minutes played, the score was level.",
        "Ninety minutes played earlier.",
        "Ninety minutes played at the end of regulation.",
        "About one hundred minutes gone.",
        "We could have one hundred and four minutes played.",
        "Are we one hundred and four minutes gone?",
        "One hundred and four minutes gone?",
        "Messi scored after twenty-two minutes played.",
    ],
)
def test_current_and_qualified_minute_references_keep_their_meaning(text):
    assert insight.wrong_claims(text, PAST) == []


def test_other_sports_do_not_use_a_football_elapsed_clock():
    assert insight.wrong_claims(WRONG, [{**PAST[-1], "sport": "basketball"}]) == []


def test_ask_retries_a_wrong_minute_even_when_the_number_is_in_the_match():
    calls = []

    def ask(*args, **kwargs):
        calls.append(kwargs)
        return {"text": WRONG if len(calls) == 1 else RIGHT}

    line = insight.checked_answer(ask, "Where are we?", PAST, [])
    assert len(calls) == 2 and calls[-1]["wrong"]
    assert line["text"] == RIGHT and line["retried"]


def test_a_wrong_minute_twice_uses_the_status_from_the_data():
    line = insight.checked_answer(lambda *a, **kw: {"text": WRONG}, "Where are we?", PAST, [])
    assert line["fallback"] and line["checked"]
    assert line["text"].startswith("Extra time, 101 minutes played.")


def test_talk_rejects_the_same_wrong_current_minute():
    assert not converse.checked({"text": WRONG}, "Where are we?", PAST, [])
