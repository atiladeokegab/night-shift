"""#407: "Lakers lead eighty-eight to ninety-five" at 95-88 (Kobe's 81, moment 11, heard
live) passed the check, both numbers being in the moment. The leader's score comes first; the
fallback and status texts already say it that way."""

import uuid

from core import fallback, insight
from data.matches import load_moments, match_header

KOBE = "0020500591"
HEADER = match_header(KOBE)
MOMENTS = load_moments(KOBE)
# The stored Haiku lines heard live, moments 11 and 3.
FLIPPED = (
    "KOBE! Thirteen feet, and he's got fifty-seven tonight! "
    "Lakers lead eighty-eight to ninety-five!"
)
TORONTO = (
    "Bryant with the jumper, thirty points, but Toronto still leads it fifty-three to sixty-nine."
)


def at(idx: int):
    i = next(i for i, m in enumerate(MOMENTS) if m["idx"] == idx)
    return MOMENTS[i], MOMENTS[:i]


def test_a_leader_said_with_its_score_last_is_wrong():
    m, past = at(11)  # Lakers 95, Raptors 88
    assert insight.wrong_numbers(FLIPPED, m, HEADER, past) == [
        "88 to 95 puts the leader's score last: say 95-88"
    ]
    m, past = at(3)  # Raptors lead 69-53, the away side
    assert insight.wrong_numbers(TORONTO, m, HEADER, past) == [
        "53 to 69 puts the leader's score last: say 69-53"
    ]


def test_the_leader_first_and_other_numbers_pass():
    m, past = at(11)
    for line in (
        "KOBE! Thirteen feet, fifty-seven tonight! Lakers lead ninety-five to eighty-eight!",
        "KOBE! Thirteen feet, fifty-seven tonight! Lakers lead 95-88!",
        "KOBE! Thirteen feet, fifty-seven tonight! Lakers lead by seven, 95 to 88.",
        "KOBE! Thirteen feet, fifty-seven tonight! Lakers ninety-five, Raptors eighty-eight.",
    ):
        assert insight.wrong_numbers(line, m, HEADER, past) == [], line


def test_a_stored_flipped_line_falls_back_to_the_leader_first():
    """The live line was a cached one: said again, it fails the check twice and the fallback,
    which says the leader first, goes out instead."""
    m, past = at(11)

    def cached(moment, history):
        return {"line_id": uuid.uuid4().hex, "match_id": KOBE, "moment_idx": 11, "text": FLIPPED}

    got = insight.checked(cached, m, past)
    assert got["fallback"] and got["text"] == fallback.fallback_text(HEADER, m)
    assert "Los Angeles Lakers lead ninety-five, eighty-eight." in got["text"]


def test_a_leader_then_its_score_then_the_other_team_is_no_margin():
    """Live 00163, moment 22 (Kobe's 80th, 121-102): "Lakers lead one twenty-one, Raptors one
    oh-two" was read as a 121-point margin and fell back to the stock line."""
    m, past = at(22)
    for line in (
        "Kobe Bryant from the line, that's eighty! Lakers lead one twenty-one, Raptors one oh-two!",
        "Kobe Bryant from the line, that's eighty! Lakers lead 121, Raptors 102!",
    ):
        assert insight.wrong_numbers(line, m, HEADER, past) == [], line
    wrong = "Kobe Bryant from the line, that's eighty! Lakers lead by twenty-one."
    assert "21 is not the margin (19)" in insight.wrong_numbers(wrong, m, HEADER, past)
