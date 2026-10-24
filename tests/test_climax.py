"""#162: the mock judges' wrong climax lines. Each moment states its chase or milestone, a lead line
whose numbers don't match its moment is said again once and then built from the moment's data,
and the analyst says at most two lines a gap."""

import asyncio
import uuid

import pytest

from core import insight
from core.replay import Replay, run_replay
from core.stats import stats
from core.store import Store
from data.matches import list_matches, load_moments, match_header, video_map

CRICKET, KOBE, JORDAN = "1298150", "0020500591", "0049700088"

# (match, moment idx, what a judge heard, a right line for the same moment)
JUDGED = [
    (
        CRICKET,
        53,
        "Byes! India need just two from the final ball, 158 for 5.",
        "Three byes! India need two from the last two balls, 158 for 5.",
    ),
    (
        CRICKET,
        52,
        "Kohli smashes a six! India 155 for 5.",
        "A wide, and a free hit! India 155 for 5, five needed from three balls.",
    ),
    (
        CRICKET,
        56,
        "Ashwin takes the single, India level at 160!",
        "Ashwin lifts it over mid-off! India win by four wickets, 160 for 6!",
    ),
    (
        CRICKET,
        14,
        "Caught! Pakistan ninety-six for five.",
        "Caught! Pakistan four for ninety-six.",
    ),
    (
        KOBE,
        22,
        "Bryant at the line, and it drops. Lakers 121, Raptors 102.",
        "Bryant at the line: that's 80 for Kobe! Lakers 121, Raptors 102.",
    ),
    (
        KOBE,
        23,
        "81 tonight: eleven twos, four threes, five free throws!",
        "Eighty-one! Kobe Bryant has 81 points, Lakers 122-102.",
    ),
    (
        KOBE,
        4,
        "Bryant from deep, but the Lakers trail fifty-eight to seventy-five.",
        "Bryant from deep, 41 for Kobe, but the Lakers still trail 65 to 75.",
    ),
    (
        JORDAN,
        30,
        "Chicago Bulls take the lead, eighty-five to eighty-six!",
        "Jordan drives and scores! The Jazz still lead, eighty-six to eighty-five.",
    ),
]


def moment(match_id, idx):
    return next(m for m in load_moments(match_id) if m["idx"] == idx)


def before(match_id, idx):
    return [m for m in load_moments(match_id) if m["idx"] < idx]


@pytest.mark.parametrize(("match_id", "idx", "heard", "right"), JUDGED)
def test_each_judged_line_is_wrong_and_its_fix_is_right(match_id, idx, heard, right):
    m, past = moment(match_id, idx), before(match_id, idx)
    assert insight.wrong_numbers(heard, m, match_header(match_id), past)
    assert insight.wrong_numbers(right, m, match_header(match_id), past) == []


def test_each_home_away_moment_says_who_leads():
    assert moment(JORDAN, 30)["detail"]["lead"] == "Utah Jazz lead 86-85"
    assert moment(JORDAN, 28)["detail"]["lead"] == "level at 83-83"
    final = load_moments("3869685")[-1]  # 3-3 after extra time, then penalties
    assert final["detail"]["lead"] == "Argentina lead the shootout 4-2"


@pytest.mark.parametrize(
    ("idx", "text", "wrong"),
    [
        (28, "Jordan ties it! The Bulls take the lead? Not yet: 83 all.", []),
        (28, "Jordan makes both, and the Bulls lead!", ["Chicago Bulls do not lead"]),
        (29, "Stockton from deep! Utah back in front, 86-83.", []),
        (28, "The Jazz led most of the night, and now it's 83 all.", []),
        (30, "Bulls take a timeout. The Jazz lead by one.", []),
    ],
)
def test_a_line_may_say_only_the_true_leader_leads(idx, text, wrong):
    m = moment(JORDAN, idx)
    assert insight.wrong_numbers(text, m, match_header(JORDAN), before(JORDAN, idx)) == wrong


def test_a_score_said_in_hundreds_is_no_margin():  # build-143: the "one" of "one hundred"
    line = "Sixty-one for Kobe, and the Lakers lead one hundred and two to ninety-three."
    m = next(m for m in load_moments(KOBE) if m["score"] == {"home": 102, "away": 93})
    assert insight.wrong_numbers(line, m, match_header(KOBE), before(KOBE, m["idx"])) == []
    spurs = load_moments("3754092")[26]  # 1-2: "two-one" is the score too
    line = "Gary Cahill! Chelsea pull one back, but Tottenham still lead two-one!"
    assert insight.wrong_numbers(line, spurs, match_header("3754092"), []) == []


@pytest.mark.parametrize(
    ("idx", "text", "wrong"),
    [
        (29, "Stockton for three! The Bulls down three.", []),
        (26, "Utah up by two.", []),
        (26, "Jazz lead by two, eighty-three to eighty-one.", []),
        (30, "Jordan scores! Bulls down one, eighty-six to eighty-five.", []),
        (30, "The Jazz lead 86-85, with 37 seconds left.", []),
        (27, "Forty for Jordan! Bulls trail eighty-three, eighty-two, 59 seconds left.", []),
        # 2 is in the moment (a 2-point basket), but the Bulls trail by one
        (30, "Jordan scores, but the Bulls are still down two.", ["2 is not the margin (1)"]),
    ],
)
def test_a_margin_is_the_score_difference(idx, text, wrong):
    m = moment(JORDAN, idx)
    assert insight.wrong_numbers(text, m, match_header(JORDAN), before(JORDAN, idx)) == wrong


def test_a_cricket_score_may_be_said_wickets_first():
    m = moment(CRICKET, 28)
    right = "Caught! India two for ten, needing one hundred fifty from one hundred balls."
    assert insight.wrong_numbers(right, m) == []
    assert insight.wrong_numbers("Caught! India three for ten.", m)  # 3.2 overs: 3 is given


# true lines from production whose counts come from recent play, or name a player by number
TRUE_FROM_RECENT_PLAY = [
    (
        CRICKET,
        11,
        "Another six! Iftikhar Ahmed blazing away, three sixes in four balls from AR Patel! "
        "Pakistan 88 for 2.",
    ),
    (CRICKET, 11, "Another six! Iftikhar Ahmed to 18 off six balls, Pakistan 88 for 2!"),
    (CRICKET, 10, "Iftikhar Ahmed, another six! Pakistan 82 for 2, three sixes in five balls!"),
    (
        JORDAN,
        28,
        "Michael Jordan ties it at eighty-three with the free throw! "
        "Forty-one points for Number 23!",
    ),
]


@pytest.mark.parametrize(("match_id", "idx", "text"), TRUE_FROM_RECENT_PLAY)
def test_a_count_from_recent_play_or_a_shirt_number_is_no_error(match_id, idx, text):
    m = moment(match_id, idx)
    assert insight.wrong_numbers(text, m, match_header(match_id), before(match_id, idx)) == []


def test_recent_play_gives_counts_only_of_the_moments_own_kind_and_player():
    m, past = moment(CRICKET, 11), before(CRICKET, 11)
    line = "Another six! Iftikhar Ahmed, three sixes in four balls! Pakistan 88 for 2."
    assert insight.wrong_numbers(line, m)  # without the recent play, 3 is not in the moment
    assert insight.wrong_numbers("Iftikhar Ahmed, five sixes in a row! 88 for 2.", m, None, past)


def test_a_chase_states_runs_needed_balls_left_and_the_result():
    chase = {m["idx"]: m["detail"].get("chase") for m in load_moments(CRICKET)}
    assert chase[53] == "India need 2 runs from the last 2 balls"
    assert chase[55] == "India need 1 run from the final ball"
    assert chase[56] == "India win by 4 wickets"
    assert chase[14] is None  # the first innings is no chase


def test_a_milestone_is_the_shooters_points_so_far():
    said = {m["idx"]: m["detail"].get("milestone") for m in load_moments(KOBE)}
    assert said[22] == "Kobe Bryant has 80 points tonight"
    assert said[23] == "Kobe Bryant has 81 points tonight"
    assert said[0] is None  # Peterson's 2 points are no milestone


def test_a_basket_in_the_thirties_or_forties_is_a_milestone_only_when_it_crosses_a_ten():
    kobe = {m["idx"]: m["detail"] for m in load_moments(KOBE)}
    assert kobe[4]["milestone"] == "Kobe Bryant has 41 points tonight"  # 30 to 41
    assert kobe[5]["player_points"] == 43 and "milestone" not in kobe[5]


def test_the_tally_never_splits_the_points_into_counts_that_dont_add_up():
    tallies = insight._tallies({}, load_moments(KOBE))
    kobe = next(t for t in tallies if t.startswith("Kobe Bryant"))
    assert kobe == "Kobe Bryant tonight: 81 points so far"


def test_a_wrong_line_is_said_again_once_then_built_from_the_moment():
    m, past = moment(KOBE, 23), load_moments(KOBE)[:23]
    said = iter(["81 tonight: eleven twos!", "Kobe Bryant, 81 points!"])
    calls = []

    def commentate(mm, history):
        calls.append(mm["idx"])
        return {"line_id": "x", "moment_idx": mm["idx"], "text": next(said)}

    assert insight.checked(commentate, m, past)["text"] == "Kobe Bryant, 81 points!"
    assert calls == [23, 23]
    calls.clear()

    def wrong(mm, history):
        calls.append(mm["idx"])
        return {"line_id": "x", "moment_idx": mm["idx"], "text": "Eleven twos!"}

    line = insight.checked(wrong, m, past)
    assert calls == [23, 23] and line["fallback"] and "eighty-one" in line["text"]
    assert insight.wrong_numbers(line["text"], m) == []


def test_every_moments_fallback_line_passes_its_own_check():
    for match in list_matches():
        header = match_header(match["match_id"])
        for m in load_moments(match["match_id"]):
            text = insight.fallback_text(header, m)
            assert insight.wrong_numbers(text, m, header) == [], (match["match_id"], m["idx"], text)


def test_a_replay_never_says_a_judged_line(tmp_path):
    wrong = {(mid, idx): heard for mid, idx, heard, _ in JUDGED}
    for match_id in (CRICKET, KOBE):

        def commentate(m, history, match_id=match_id):
            # a Stat moment carries the idx it follows: only the moment's own line is judged
            key = (match_id, m["idx"]) if m["type"] != "Stat" else None
            text = wrong.get(key, f"{m['type']} {uuid.uuid4().hex}")
            return {"line_id": uuid.uuid4().hex, "moment_idx": m["idx"], "text": text}

        r, store = Replay(match_id, 1e9), Store(tmp_path / match_id)
        moments, vmap = load_moments(match_id), video_map(match_id)
        asyncio.run(run_replay(r, moments, commentate, store, vmap))
        said = [e["data"]["text"] for e in r.events if e["event"] == "line"]
        assert said and not set(said) & set(wrong.values())
        assert [ln["text"] for ln in store.all("lines")] == said


def test_the_analyst_says_at_most_two_lines_a_gap(tmp_path):
    r, store = Replay(KOBE, 1e9), Store(tmp_path)

    def commentate(m, history):
        said = uuid.uuid4().hex.translate(str.maketrans("0123456789", "ghijklmnop"))  # no number
        return {"line_id": uuid.uuid4().hex, "moment_idx": m["idx"], "text": said}

    asyncio.run(run_replay(r, load_moments(KOBE), commentate, store, video_map(KOBE)))
    lines = [e["data"] for e in r.events if e["event"] == "line"]
    per_gap = {}
    for ln in lines:
        if "insight" in ln:
            per_gap[ln["insight"]["after_idx"]] = per_gap.get(ln["insight"]["after_idx"], 0) + 1
    assert per_gap and max(per_gap.values()) == 2


def auto_fixed(tmp_path, texts):
    """One replay of Kobe's 80th point whose lead says `texts` in turn; what it corrected."""
    said, sent = iter(texts), []

    def commentate(m, history):
        return {
            "line_id": uuid.uuid4().hex,
            "match_id": KOBE,
            "moment_idx": m["idx"],
            "text": next(said),
        }

    def correct(line, text):
        sent.append((line["text"], text))
        return {"mubit_request_id": "m1", "reply_matched": True, "recorded": True}

    r, store = Replay(KOBE, 1e9), Store(tmp_path)
    asyncio.run(run_replay(r, [moment(KOBE, 22)], commentate, store, correct=correct))
    return sent, store


WRONG_80, RIGHT_80 = JUDGED[4][2], JUDGED[4][3]


def test_a_rejected_first_try_is_corrected_once_to_the_kept_line(tmp_path):
    sent, store = auto_fixed(tmp_path, [WRONG_80, RIGHT_80])
    assert sent == [(WRONG_80, RIGHT_80)]
    [fix] = store.all("auto_fixes")
    assert store.all("fixes") == []  # the review queue reads `fixes` as the people's
    assert (
        fix["reason"] == "auto: number check" and fix["auto"] and fix["corrected_text"] == RIGHT_80
    )
    [line] = store.all("lines")
    assert line["text"] == RIGHT_80 and "rejected" not in line


def test_a_fallback_is_never_sent_as_a_correction(tmp_path):
    sent, store = auto_fixed(tmp_path, [WRONG_80, WRONG_80])
    assert sent == [] and store.all("auto_fixes") == []
    assert store.all("lines")[0]["fallback"]


def test_a_line_right_first_time_sends_no_correction(tmp_path):
    sent, store = auto_fixed(tmp_path, [RIGHT_80])
    assert sent == [] and store.all("auto_fixes") == []


def test_an_auto_fix_is_counted_apart_from_the_peoples(tmp_path):
    _, store = auto_fixed(tmp_path, [WRONG_80, RIGHT_80])
    s = stats(store)
    assert s["fixes_auto"] == 1 and s["fixes_recorded"] == 0 and s["fixes_toward_next"] == 0
    # the producer's fix-list corrections in prod stay "your fixes"
    fix = {"reason": "fix list: wrong number", "recorded": True, "created_at": "2026-10-24T12"}
    store.append("fixes", fix)
    s = stats(store)
    assert s["fixes_auto"] == 1 and s["fixes_recorded"] == 1 and s["fixes_toward_next"] == 1


# lines the model said aloud at India v Pakistan idx 52, reasoning about its input
SELF_TALK = [
    "The recent play and current score confirm a six at 19.4, not a wide.",
    "Wait—I need to reconcile the information. The six listed in recent play",
    "Wait—I need to reconsider. The recent play lists 19.4 as a Six by V Kohli.",
    "Wait—the recent play shows a six at 19.4, but the moment given is a wide at 19.4.",
]


@pytest.mark.parametrize("text", SELF_TALK)
def test_a_line_that_talks_to_itself_is_wrong(text):
    assert insight.talks_to_itself(text)
    assert "the line talks to itself" in insight.wrong_numbers(text, moment(CRICKET, 52))


@pytest.mark.parametrize(
    "text",
    [
        "Big appeal! They'll have to wait for the review, India 155 for 5.",
        "Wait for it... a wide! India 155 for 5.",
        "That was actually a wide from Nawaz, India 155 for 5.",
    ],
)
def test_waiting_in_a_sports_sense_is_commentary(text):
    assert not insight.talks_to_itself(text)
    assert insight.wrong_numbers(text, moment(CRICKET, 52)) == []


def test_a_line_that_talks_to_itself_is_said_again_once():
    said = iter(
        [
            "Wait—I need to reconsider the moment given.",
            "A wide from Nawaz on the free hit! India 155 for 5.",
        ]
    )

    def commentate(mm, history):
        return {"line_id": "x", "moment_idx": mm["idx"], "text": next(said)}

    line = insight.checked(commentate, moment(CRICKET, 52), before(CRICKET, 52))
    assert line["text"] == "A wide from Nawaz on the free hit! India 155 for 5."


KOBE_14 = "Kobe Bryant from deep! Lakers lead by twelve, 108 to 96, under six minutes left."

# real lines the check flagged although true, each with the insight or reply it was said as
TRUE_LINES = [
    (  # "lead" the noun: a lead that was, not a claim that the Jazz lead now
        "Chicago have taken four of the last six key moments, Utah two, and a 66-62 Jazz lead "
        "has become 77-77.",
        {
            "match_id": JORDAN,
            "after_idx": 23,
            "n": 5,
            "kind": "momentum",
            "detail": "Momentum, the last 6 key moments from period 4, 11:44: Chicago Bulls 4, "
            "Utah Jazz 2; the score went from 66-62 to 77-77 (home-away)",
            "heard": "It's 77-77 and the last thing to change it was that Bulls free throw at "
            "04:46.",
        },
    ),
    (  # Kobe had scored the last six key moments
        "Kobe's on fire in the fourth quarter! Three straight buckets, and the Lakers pull away, "
        "108 to 96.",
        {
            "match_id": KOBE,
            "after_idx": 14,
            "n": 7,
            "kind": "reply",
            "detail": KOBE_14,
            "heard": KOBE_14,
        },
    ),
    (  # said just after Malone's Free Throw 2 of 2
        "Karl Malone puts Utah ahead with two free throws, seventy-five to seventy-four!",
        {
            "match_id": JORDAN,
            "after_idx": 22,
            "n": 15,
            "kind": "reply",
            "detail": "Karl Malone from the line, both shots good! Utah takes the lead, "
            "seventy-five to seventy-four!",
            "heard": "Karl Malone from the line, both shots good! Utah takes the lead, "
            "seventy-five to seventy-four!",
        },
    ),
]


def over(said_as, text):
    key = "reply" if said_as["kind"] == "reply" else "insight"
    *past, m = insight.said_over({"text": text, key: said_as}, load_moments)
    return m, past


@pytest.mark.parametrize(("text", "said_as"), TRUE_LINES)
def test_a_true_line_the_check_flagged_passes(text, said_as):
    m, past = over(said_as, text)
    assert insight.wrong_numbers(text, m, match_header(said_as["match_id"]), past) == []


@pytest.mark.parametrize(
    ("i", "text"),
    [
        (0, "And the Jazz lead, 77-77."),  # a claim, at a level score
        (0, "The Jazz in front, 77-77."),
        (1, "Kobe's on fire! Seven straight buckets, 108 to 96."),  # he scored the last six
        (2, "Karl Malone puts Utah ahead with three free throws!"),
    ],
)
def test_the_same_shapes_stay_wrong_when_false(i, text):
    said_as = TRUE_LINES[i][1]
    m, past = over(said_as, text)
    assert insight.wrong_numbers(text, m, match_header(said_as["match_id"]), past)


def test_a_lead_after_a_score_is_still_a_claim():
    line = "At 86-85 Utah lead by one."
    assert (
        insight.wrong_numbers(line, moment(JORDAN, 30), match_header(JORDAN), before(JORDAN, 30))
        == []
    )
    wrong = insight.wrong_numbers(
        line, moment(JORDAN, 32), match_header(JORDAN), before(JORDAN, 32)
    )
    assert "Utah Jazz do not lead" in wrong  # 86-87: the Bulls lead


def test_in_front_of_a_crowd_is_no_lead():
    m = moment(JORDAN, 23)
    line = "Rodman ties it at 77, the Jazz in front of a stunned home crowd."
    assert insight.wrong_numbers(line, m, match_header(JORDAN), before(JORDAN, 23)) == []
