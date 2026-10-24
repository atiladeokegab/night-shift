"""#195: the line said when the commentator's stays wrong is a plain sentence a blind listener can
follow, built only from the moment's data, never over 20 words, and right on its own numbers."""

import re

import pytest

from core import insight
from core.fallback import hoops, words
from data.matches import list_matches, load_moments, match_header

ALL = [(match["match_id"], m) for match in list_matches() for m in load_moments(match["match_id"])]
SAID = {  # (match, idx): the line a listener hears
    ("3869685", 46): "Lionel Messi shoots from twenty-three yards, saved by Hugo Lloris. "
    "Level at two all.",
    ("0049700088", 9): "Michael Jordan with the layup. Chicago Bulls lead thirty-six, thirty-five.",
    ("0020500591", 20): "Kobe Bryant makes the free throw, seventy-nine points tonight. "
    "Los Angeles Lakers lead one twenty, one oh-two.",
    ("1298150", 50): "V Kohli, two runs. India need thirteen from three balls. "
    "India one hundred and forty-seven for five.",
    (
        "9636",
        3,
    ): "Esteban Ocon passes Yuki Tsunoda for third place. Lap twenty-eight of sixty-nine.",
    ("3754092", 28): "Ryan Mason comes on for Son Heung-Min. Tottenham Hotspur lead two, one.",
}


@pytest.mark.parametrize("key", SAID)
def test_a_fallback_reads_like_a_commentator(key):
    match_id, idx = key
    m = next(m for mid, m in ALL if mid == match_id and m["idx"] == idx)
    assert insight.fallback_text(match_header(match_id), m) == SAID[key]


def test_every_fallback_is_short_right_and_free_of_raw_labels():
    assert {mid for mid, _ in ALL} == {
        "3869685",
        "3754092",
        "0020500591",
        "0049700088",
        "1298150",
        "9636",
    }
    for match_id, m in ALL:
        header = match_header(match_id)
        text = insight.fallback_text(header, m)
        where = (match_id, m["idx"], text)
        assert len(text.split()) <= 20, where
        assert insight.wrong_numbers(text, m, header) == [], where
        assert not re.search(r"\d|Off T|Field goal|\bpoints?,|Wayward", text), where


def test_numbers_are_said_as_the_check_hears_them():
    for n in range(1000):
        assert insight.said(words(n)) == ([n] if n != 1 else ["one"]), n
        assert insight.said(f"lead {hoops(n)}")[1:] == ([n] if n != 1 else ["one"]), n


def test_a_score_after_lead_is_not_read_as_a_margin():
    m = next(m for mid, m in ALL if mid == "0020500591" and m["idx"] == 20)  # 120-102
    header = match_header("0020500591")

    def margins(text):
        return [w for w in insight.wrong_numbers(text, m, header) if "margin" in w]

    assert margins("Los Angeles Lakers lead one twenty, one oh-two.") == []
    assert margins("Los Angeles Lakers lead by four.") == ["4 is not the margin (18)"]
