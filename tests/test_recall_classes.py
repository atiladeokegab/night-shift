"""#293: the classes of wrong line the number check used to miss, as general rules: a clock said to
the second, a streak, runs over a span of balls, how a shot ended, the shootout's score, and a
level claim on any football moment. Each rule must also let the right line through."""

import pytest

from core import insight
from data.matches import load_moments, match_header

LAKERS, JAZZ = "0020500591", "0049700088"
ASIA_CUP, NEPAL = "1298150", "1515217"
FINAL, SPURS = "3869685", "3754092"


def check(match_id: str, idx: int, text: str) -> list[str]:
    """The number check on a line said at this moment, as the replay runs it."""
    moments = load_moments(match_id)
    at = next(i for i, m in enumerate(moments) if m["idx"] == idx)
    return insight.wrong_numbers(text, moments[at], match_header(match_id), moments[:at])


WRONG = [
    # the clock reads 1:45: ninety seconds is a quarter-minute off
    (JAZZ, 4, "Ninety seconds to go in the quarter and the Jazz edge in front!", "seconds"),
    (JAZZ, 4, "Under a minute... under sixty seconds left and Utah score!", "seconds"),
    # Iftikhar's sixes came at 11.1 and 11.3: he kept the strike, so 11.2 was his and no six
    (ASIA_CUP, 10, "Iftikhar again! Back-to-back sixes!", "in a row"),
    (ASIA_CUP, 11, "Three sixes in a row for Iftikhar!", "in a row"),
    (ASIA_CUP, 9, "Iftikhar Ahmed, consecutive sixes off Ashwin and Patel!", "in a row"),
    # the Bulls scored between the Jazz's two baskets
    (JAZZ, 7, "Back-to-back buckets for Utah!", "in a row"),
    # Iftikhar's last four balls brought 18, the last six 24
    (ASIA_CUP, 11, "Iftikhar has 24 off four balls!", "off 4 balls"),
    # how the shot ended
    (FINAL, 4, "Blocked! Messi's shot hits a defender.", "blocked is called"),
    (FINAL, 1, "Saved by the keeper, a good stop.", "a save is called"),
    (FINAL, 13, "It flies wide of the post!", "off target is called"),
    # Argentina lead the shootout 2-1; the match score is 3-3
    (FINAL, 63, "Saved! It's three-three in the shootout!", "not the shootout"),
    # a level claim on a save at 1-2
    (SPURS, 27, "Great save from Lloris, and it's still level!", "not level"),
]


@pytest.mark.parametrize(("match_id", "idx", "text", "why"), WRONG)
def test_a_wrong_line_of_each_class_is_caught(match_id, idx, text, why):
    wrong = check(match_id, idx, text)
    assert any(why in r for r in wrong), wrong


RIGHT = [
    (JAZZ, 4, "About ninety seconds left in the quarter!"),
    (JAZZ, 4, "Over ninety seconds to play, Utah ahead by one!"),
    (JAZZ, 4, "A hundred and five seconds left in the first quarter."),
    (ASIA_CUP, 11, "Back-to-back sixes for Iftikhar!"),
    (ASIA_CUP, 11, "Iftikhar has 18 off four balls!"),
    (ASIA_CUP, 11, "Iftikhar has 24 off six balls!"),
    (ASIA_CUP, 11, "His third six in four balls!"),
    # de Leede's four came after his four off the last ball of an over: the strike passed, so
    # whether he had the balls between is unknown, and the streak is not called wrong
    (NEPAL, 8, "Back-to-back fours for de Leede!"),
    # the championships are not the moment's play
    (JAZZ, 7, "Chasing back-to-back championships, Utah score again!"),
    (FINAL, 4, "Messi fires it wide!"),
    (FINAL, 0, "Lloris gets down to block it with his body, saved!"),
    (FINAL, 63, "Wide! Still three-three, and Argentina lead the shootout two-one."),
    (SPURS, 27, "Great save from Lloris! Chelsea still trail by one."),
    (SPURS, 27, "Saved! Can Chelsea get level?"),
]


@pytest.mark.parametrize(("match_id", "idx", "text"), RIGHT)
def test_a_right_line_of_each_class_passes(match_id, idx, text):
    assert check(match_id, idx, text) == []
