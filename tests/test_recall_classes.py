"""#293: the classes of wrong line the number check used to miss, as general rules: a clock said to
the second, a basketball streak, runs over a span of balls, how a shot ended, the shootout's score,
and a level claim on any football moment. Each rule must also let the right line through."""

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
    (JAZZ, 4, "One minute thirty seconds left.", "seconds"),
    (JAZZ, 4, "Under ninety seconds left.", "seconds"),
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
    (JAZZ, 4, "One minute forty-five seconds left."),
    (JAZZ, 4, "A minute and 45 seconds to go!"),
    (JAZZ, 4, "Nineteen seconds left on the shot clock."),
    (JAZZ, 4, "Nineteen seconds remaining on the shot clock."),
    # a streak that is negated, needed or in the past is no claim about the play now
    (JAZZ, 7, "No back-to-back buckets for Utah; Chicago scored between them."),
    (JAZZ, 7, "Utah need back-to-back buckets."),
    # a cricket streak is not tested: the moments may not hold the ball that breaks it
    (ASIA_CUP, 11, "Back-to-back sixes for Iftikhar!"),
    (NEPAL, 8, "Back-to-back fours for de Leede!"),
    (ASIA_CUP, 30, "Back-to-back fours for Suryakumar Yadav!"),
    (ASIA_CUP, 11, "Iftikhar has 18 off four balls!"),
    (ASIA_CUP, 11, "Iftikhar has 24 off six balls!"),
    (ASIA_CUP, 11, "His third six in four balls!"),
    # the championships are not the moment's play
    (JAZZ, 7, "Chasing back-to-back championships, Utah score again!"),
    (FINAL, 4, "Messi fires it wide!"),
    (FINAL, 1, "Di María's shot is blocked and goes wide!"),
    (FINAL, 0, "Lloris gets down to block it with his body, saved!"),
    (FINAL, 0, "Saved! The ball stays in, not wide."),
    (FINAL, 0, "Saved by Lloris! That shot wasn't wide."),
    (FINAL, 63, "Wide! Still three-three, and Argentina lead the shootout two-one."),
    (SPURS, 27, "Great save from Lloris! Chelsea still trail by one."),
    (SPURS, 27, "Saved! Can Chelsea get level?"),
    # level in the past, or level with a player, says nothing of the score now
    (SPURS, 27, "They were level at kick-off; Lloris makes the save."),
    (SPURS, 27, "They were all square at kick-off; Lloris makes the save."),
    (SPURS, 27, "Saved! Kane was played on, still level with the last defender."),
]


@pytest.mark.parametrize(("match_id", "idx", "text"), RIGHT)
def test_a_right_line_of_each_class_passes(match_id, idx, text):
    assert check(match_id, idx, text) == []
