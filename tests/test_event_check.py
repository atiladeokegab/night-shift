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


@pytest.mark.parametrize(
    "text", ["Argentina score again!", "France scored! Two-one!", "Argentina have scored again!"]
)
@pytest.mark.parametrize("idx", [13, 30])  # a saved shot; an injury stoppage, the ball in play
def test_a_team_said_to_score_when_none_did_is_a_goal_called(text, idx):
    # build-130: the plural "Argentina score again" got past the singular "scores"
    wrong = insight.wrong_event(text, moment(FINAL, idx))
    assert any(w.startswith("a goal is called") for w in wrong), wrong


@pytest.mark.parametrize(
    ("idx", "text"),
    [
        (13, "Saved! Argentina's score stays at two."),
        (13, "Argentina score is still two-nil, Lloris saves."),
        (13, "Saved by Lloris! The score is two-nil."),
        (9, "Argentina score again! Di María makes it two!"),
    ],
)
def test_the_score_and_a_real_goal_pass(idx, text):
    assert insight.wrong_event(text, moment(FINAL, idx)) == []


JAZZ, KOBE, INDIA = "0049700088", "0020500591", "1298150"

# (match, idx, a line heard on the live site, a near miss that must pass): the #190 audit's classes
OTHER_SPORTS = [
    # a two called a three; "from fifteen feet" and a real three "from downtown" are right
    (
        JAZZ,
        24,
        "Ron Harper from downtown, he ties it up! Seventy-nine all with three forty-four to play!",
        "Ron Harper from fifteen feet! Seventy-nine all with three forty-four to play!",
    ),
    (KOBE, 24, "Matt Bonner from deep! Toronto cuts it to eighteen, Lakers 122!", None),
    (KOBE, 4, None, "Kobe Bryant from downtown, assisted by Devean George!"),
    # a tie called when India won by 4 wickets; "160 for six" is runs for wickets
    (
        INDIA,
        56,
        "Ashwin takes a run! India level the scores at 160, and they've forced a Super Over!",
        "Ashwin takes the single! India 160 for six, they win by four wickets!",
    ),
    (INDIA, 56, "Ashwin takes a run off the final ball! They've matched Pakistan's total!", None),
    # a six called on three byes and on a wide; "Pakistan six for one" is a score
    (
        INDIA,
        53,
        "Kohli with a six! India 158 for 5, needing just 2 runs from the last two balls!",
        "Three byes off Nawaz! Kohli was the man who took Pakistan six for one, years ago.",
    ),
    (INDIA, 52, "Kohli! SIX! India have 155 for 5, need just 5 more from 3 balls!", None),
    # a six found or hit "for six" is a six; only a wanted one or a score is not
    (INDIA, 53, "Kohli finds a six over long-on!", None),
    (INDIA, 53, "KOHLI FINDS A SIX!", None),
    (INDIA, 53, "Kohli hits it FOR SIX!", None),
    (INDIA, 53, "KOHLI GOES FOR SIX! INDIA WIN!", None),
    # a run out called a stumping; "bowled" names the bowler and "run out of" is no dismissal
    (
        INDIA,
        32,
        "Patel run out! Rizwan with the stumping, India 31 for 4, need 129 from 83 balls.",
        "Patel run out! Rizwan with the direct hit, bowled by Shadab Khan.",
    ),
    (INDIA, 54, None, "KD Karthik is stumped! India can't afford to run out of batters now."),
]


@pytest.mark.parametrize(("match_id", "idx", "heard", "right"), OTHER_SPORTS)
def test_basketball_and_cricket_wrong_events_are_rejected_and_near_misses_pass(
    match_id, idx, heard, right
):
    m = moment(match_id, idx)
    if heard:
        assert insight.wrong_event(heard, m)
    if right:
        assert insight.wrong_event(right, m) == []


@pytest.mark.parametrize(
    ("idx", "heard", "right"),
    [
        # a wrong leader (Utah lead 86-85): wrong_numbers' _false_lead, not wrong_event
        (
            30,
            "Michael Jordan with the layup! Chicago Bulls take the lead, 85-86, thirty-seven"
            " seconds remaining!",
            "Michael Jordan with the layup! Utah lead 86-85, thirty-seven seconds left!",
        ),
        (31, None, "STOLEN BY JORDAN! The Bulls take it away, 86-85!"),
    ],
)
def test_a_wrong_leader_from_the_audit_is_still_caught(idx, heard, right):
    m = moment(JAZZ, idx)
    if heard:
        assert insight.wrong_numbers(heard, m, match_header(JAZZ))
    assert insight.wrong_numbers(right, m, match_header(JAZZ)) == []


def test_the_model_talking_to_itself_from_the_audit_is_still_caught():
    m = moment(INDIA, 52)
    heard = "Wait—the recent play shows a six at 19.4, but the moment given is a wide at 19.4."
    assert insight.wrong_numbers(heard, m, match_header(INDIA))
    assert insight.talks_to_itself("Given that the Event parameter explicitly defines what")
    assert not insight.talks_to_itself("Kohli has to wait for his free hit!")
    assert not insight.talks_to_itself("The moment of the match! Kohli wins it for India!")


def test_f1_is_not_checked():
    m = load_moments("9636")[0]
    assert insight.wrong_event("Lights out! A six-car pile-up into turn one!", m) == []


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


# Right lines the event check flagged; each must pass at its moment
NEAR_MISSES = [
    # the match is level at 3-3 through the shootout, which is counted on its own
    (FINAL, 59, "Mbappé converts! Still three all, and France lead the shootout one-nil."),
    (FINAL, 59, "Mbappé scores from the spot. The match is level at three all."),
    # cricket: a six wanted is no six hit, and "FOR SIX" is runs for wickets
    (INDIA, 53, "Three byes! India need a six off the last ball now!"),
    (INDIA, 53, "Three byes off Nawaz. Can Kohli find a six?"),
    (INDIA, 53, "Three byes! Unless Kohli finds a six, it's Pakistan's."),
    (INDIA, 53, "Three byes. India needed a six there and didn't get one."),
    (INDIA, 56, "INDIA WIN BY FOUR WICKETS! 160 FOR SIX!"),
    (INDIA, 56, "India win by four wickets! 160 for SIX!"),
    (INDIA, 56, "India were level on the run-rate all night, and they win by four wickets!"),
    (INDIA, 56, "India were level with the run rate all night, and they win by four wickets!"),
    # a three from earlier play, recalled on a two
    (JAZZ, 24, "Harper, who hit from deep earlier, now a fifteen-footer!"),
    # a team's goals recalled on a save
    (FINAL, 13, "Argentina scored twice in the first half; Lloris saves this one."),
    (FINAL, 13, "Lloris saves from De Paul. France have scored none so far."),
]


@pytest.mark.parametrize(("match_id", "idx", "text"), NEAR_MISSES)
def test_a_right_line_the_event_check_used_to_flag_passes(match_id, idx, text):
    assert insight.wrong_event(text, moment(match_id, idx)) == []


@pytest.mark.parametrize(
    ("idx", "text"),
    [
        (59, "Mbappé converts from the spot! France level it up, three all!"),  # France lead it 0-1
        (67, "MONTIEL! ARGENTINA LEVEL IT! Four-two in the shootout!"),  # the winning kick
        (25, "Mbappé levels it from the penalty spot! Argentina two, France one!"),
    ],
)
def test_a_kick_that_levels_nothing_is_still_caught(idx, text):
    wrong = insight.wrong_event(text, moment(FINAL, idx))
    assert wrong and "not level" in wrong[0], wrong
    assert ("shootout" in wrong[0]) == (idx != 25)  # the reason names the score it checked
