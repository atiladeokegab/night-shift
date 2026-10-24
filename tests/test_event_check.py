"""#188: a football line that calls the wrong kind of event (a miss as a goal, a booking as a
penalty, a shot wide as saved) is rejected like a wrong number: said again once, then built from
the moment's data. The wrong lines are the live final's, heard on 24 October."""

import pytest

from core import insight
from data.matches import list_matches, load_moments, match_header

FINAL, SPURS = "3869685", "3754092"


def moment(match_id, idx):
    return next(m for m in load_moments(match_id) if m["idx"] == idx)


# (moment idx in the final, what the live site said, a right line for the same moment)
HEARD = [
    (18, "MESSI! ARGENTINA TWO, FRANCE NOTHING!", "Messi drags it wide! Argentina still two up."),
    (
        28,
        "Foul in the box! Marcus Thuram picks up yellow. Penalty to Argentina, level at two-two.",
        "Marcus Thuram goes down in the box and is booked for it! Still two-two.",
    ),
    (
        59,
        "Mbappé converts from the spot! France level it up, three all in the penalty shootout!",
        "Mbappé converts from the spot! France lead the shootout one-nil.",
    ),
    (
        63,
        "Tchouaméni's penalty saved! Argentina lead 2-1 in the shootout, still level at three all.",
        "Tchouaméni drags his penalty wide! Argentina lead the shootout two-one.",
    ),
]


@pytest.mark.parametrize(("idx", "heard", "right"), HEARD)
def test_the_live_finals_wrong_event_lines_are_rejected_and_right_ones_pass(idx, heard, right):
    m = moment(FINAL, idx)
    assert insight.wrong_event(heard, m)
    assert insight.wrong_event(right, m) == []
    # through the number check, so checked() and the review queue see it too
    assert insight.wrong_numbers(heard, m, match_header(FINAL))


@pytest.mark.parametrize(
    ("match_id", "idx", "text"),
    [
        # the score only: "the scores", "level at", "two to level it", "who scored"
        (FINAL, 57, "Martínez saves it! The scores level at three-three."),
        (FINAL, 60, "Messi from the spot! Argentina level, one all in the shootout!"),
        (SPURS, 17, "Two to level it, and a long way back from there."),
        (FINAL, 53, "Montiel, who scored in the group stage, gives away a penalty! Yellow card."),
        # a recap at full time names the last goal
        (FINAL, 68, "And Montiel scores! Argentina win the World Cup!"),
        # a draw is level
        (FINAL, 26, "Mbappé levels it! Two-two!"),
        (FINAL, 45, "Lautaro Martínez with a half volley from sixteen yards, but it drifts wide!"),
    ],
)
def test_lines_that_say_the_event_right_pass(match_id, idx, text):
    assert insight.wrong_event(text, moment(match_id, idx)) == []


@pytest.mark.parametrize(
    ("match_id", "idx", "text"),
    [
        (SPURS, 26, "Gary Cahill levels it! Chelsea one, Tottenham Hotspur two."),
        (FINAL, 25, "Mbappé levels it from the spot! Argentina two, France one!"),
        (FINAL, 57, "GOAL! Kolo Muani!"),
        (FINAL, 18, "Messi scores! Argentina three-nil!"),
    ],
)
def test_more_wrong_events_from_the_live_store(match_id, idx, text):
    assert insight.wrong_event(text, moment(match_id, idx))


def test_other_sports_are_not_checked():
    kobe = load_moments("0020500591")[22]
    assert insight.wrong_event("Kobe makes it 120-102!", kobe) == []


def test_the_leads_reply_over_a_stat_recalls_a_goal_and_passes():
    stat = insight.stat_moment(moment(FINAL, 9), {"heard": "Two goals in 36 minutes."}, reply=True)
    assert stat["type"] == "Stat"
    assert insight.wrong_event("Di María makes it two!", stat) == []


def test_a_wrong_event_is_said_again_once_then_built_from_the_moment():
    m, past = moment(FINAL, 63), load_moments(FINAL)[:63]
    said = iter([HEARD[3][1], HEARD[3][2]])
    calls = []

    def commentate(mm, history):
        calls.append(mm["idx"])
        return {"line_id": "x", "moment_idx": mm["idx"], "text": next(said)}

    assert insight.checked(commentate, m, past)["text"] == HEARD[3][2]
    assert calls == [63, 63]
    calls.clear()

    def wrong(mm, history):
        calls.append(mm["idx"])
        return {"line_id": "x", "moment_idx": mm["idx"], "text": HEARD[3][1]}

    line = insight.checked(wrong, m, past)
    assert calls == [63, 63] and line["fallback"] and "saved" not in line["text"].lower()


def test_every_football_fallback_line_passes_the_event_check():
    for match in list_matches():
        for m in load_moments(match["match_id"]):
            text = insight.fallback_text(match_header(match["match_id"]), m)
            assert insight.wrong_event(text, m) == [], (match["match_id"], m["idx"], text)
