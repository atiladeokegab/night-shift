"""Football moments say where (#172): a zone, or a shot's distance and side, from StatsBomb x, y."""

import pytest

from core.insight import wrong_numbers
from data.matches import _where, load_moments

FINAL = "3869685"  # Argentina v France, the 2022 World Cup final


def at(x, y, kind="Foul Committed"):
    return {"type": kind, "x": x, "y": y}


@pytest.mark.parametrize(
    ("x", "y", "zone"),
    [
        (108, 40, "inside the box"),  # the penalty spot
        (102, 40, "on the edge of the box"),
        (90, 5, "on the left wing"),  # in the opponent's half
        (90, 75, "on the right wing"),
        (40, 40, "in their own half"),
        (116, 40, "inside the six-yard box"),
        (10, 40, "inside their own box"),
        (80, 40, "in the opponent's half"),
    ],
)
def test_an_event_says_its_zone(x, y, zone):
    assert _where(at(x, y)) == zone


@pytest.mark.parametrize(
    ("x", "y", "where"),
    [
        (108, 40, "from 12 yards, central"),
        (102, 46, "from 19 yards, right of centre"),
        (100, 10, "from 36 yards, wide on the left"),
        (119.5, 40, "from 1 yard, central"),
    ],
)
def test_a_shot_says_its_distance_and_side(x, y, where):
    assert _where(at(x, y, "Shot")) == where


def test_left_is_left_on_a_real_goal():
    # Di María's goal in the final, 36th minute: he ran onto Mac Allister's pass on the left and
    # finished across Lloris. StatsBomb puts it at (111.8, 32.1): y < 40 is the attackers' left.
    goal = load_moments(FINAL)[9]
    assert (goal["players"]["shooter"], goal["outcome"]) == ("Ángel Di María", "Goal")
    assert goal["detail"]["where"] == "from 11 yards, left of centre"


def test_every_located_football_moment_says_where_and_no_other_sport_does():
    for m in load_moments(FINAL) + load_moments("3754092"):
        assert ("where" in m["detail"]) == ("x" in m)
    for mid in ("0020500591", "1298150", "9636"):
        assert not any("where" in m["detail"] for m in load_moments(mid))


def test_the_number_check_takes_a_where_distance_as_given():
    penalty = load_moments(FINAL)[5]  # Messi's penalty: from 12 yards, central
    assert penalty["detail"]["where"] == "from 12 yards, central"
    assert wrong_numbers("Messi from twelve yards, and Argentina lead!", penalty) == []
    assert wrong_numbers("Messi from 20 yards, and Argentina lead!", penalty) == [
        "20 is not in the moment"
    ]
