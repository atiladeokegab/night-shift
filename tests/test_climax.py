"""#162: the mock judges' wrong climax lines. Each moment states its chase or milestone, a lead line
whose numbers don't match its moment is said again once and then built from the moment's data,
and the analyst says at most two lines a gap."""

import asyncio
import uuid

import pytest

from core import insight
from core.replay import Replay, run_replay
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
    assert calls == [23, 23] and line["fallback"] and "81" in line["text"]
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
        return {"line_id": uuid.uuid4().hex, "moment_idx": m["idx"], "text": uuid.uuid4().hex}

    asyncio.run(run_replay(r, load_moments(KOBE), commentate, store, video_map(KOBE)))
    lines = [e["data"] for e in r.events if e["event"] == "line"]
    per_gap = {}
    for ln in lines:
        if "insight" in ln:
            per_gap[ln["insight"]["after_idx"]] = per_gap.get(ln["insight"]["after_idx"], 0) + 1
    assert per_gap and max(per_gap.values()) == 2
