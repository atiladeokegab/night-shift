"""The analyst's stat lines and the lead's replies get the moment lines' number check: a wrong
number gets the same stat once more, then the line is dropped, never said. The wrong lines are the
prod store's, said on 24 October before the check covered them."""

import functools
import uuid
from collections import Counter

import pytest

from agent import commentator
from core import insight
from core.store import Store
from data.matches import load_moments, match_header
from tests.test_insight import KOBE, Fake, gap, letters, replay

BULLS, ASIA = "0049700088", "1298150"


def check(match_id, after_idx, kind, detail, heard, text):
    said_as = {"match_id": match_id, "after_idx": after_idx, "kind": kind, "detail": detail}
    said_as["heard"] = heard
    role = "reply" if kind == "reply" else "insight"
    *past, m = insight.said_over({"text": text, role: said_as}, load_moments)
    return insight.wrong_numbers(text, m, match_header(match_id), past)


RODMAN = "Dennis Rodman strips it away! Chicago Bulls trail 83 to 81, under two minutes left."
KOBE74 = "Kobe Bryant unstoppable tonight, 74 points and counting – Lakers dominating, 115 to 98."
JORDAN = (
    "Michael Jordan (Chicago Bulls), before tonight (1997-10-31 to 1998-06-13, 102 games): made "
    "1109 of 2384 (47%). Tonight so far: 14 of 34 attempts. Chance now, before tonight and tonight "
    "combined: 42%."
)
PANDYA = (
    "HH Pandya (India), before tonight (2022-01-01 to 2022-10-22, 19 games). - Bowling: 12 wickets "
    "in 276 balls, economy 8.65 before tonight; 9 runs and 0 wickets off 6 balls tonight"
)
KOBE_72 = (
    "Kobe Bryant tonight, in the key moments so far: Field goal (2 points) x10, Field goal "
    "(3 points) x4; 72 points in all"
)
IFTIKHAR = "Iftikhar Ahmed tonight, in the key moments so far: Four (4 runs) x2, Six (6 runs) x4"
KOHLI = "V Kohli tonight, in the key moments so far: Six (6 runs) x2, Four (4 runs) x6"
CHASE = (
    "Score story: India 158 for 5, 2 more needed to reach 160; the last change at 19.1: India "
    "Wicket, caught"
)

# (match, moment, kind, the stat or what the analyst said, what the partner heard, the prod line)
WRONG = [
    (BULLS, 26, "reply", RODMAN, RODMAN, "Bulls down three to 81, ninety seconds remaining!"),
    (BULLS, 30, "player profile", JORDAN, "", "Chicago Bulls take the lead, 85 to 86!"),
    (ASIA, 6, "player profile", PANDYA, "", "Pakistan fifty for two, finding their rhythm."),
    (ASIA, 53, "score story", CHASE, "", "India need 2 runs from the final delivery to win!"),
    (KOBE, 16, "tally", KOBE_72, "", "Thirty-four in the fourth alone—eighty-one for the game!"),
    (KOBE, 17, "reply", KOBE74, KOBE74, "Kobe Bryant with another bucket, seventy-six points now."),
    (ASIA, 12, "tally", IFTIKHAR, "", "Four sixes and two fours: 28 runs in boundaries alone."),
    (ASIA, 46, "tally", KOHLI, "", "Six fours, two sixes. That's 40 of his runs in boundaries."),
]


@pytest.mark.parametrize(("match_id", "idx", "kind", "detail", "heard", "text"), WRONG)
def test_a_wrong_number_in_a_prod_analyst_line_is_caught(match_id, idx, kind, detail, heard, text):
    assert check(match_id, idx, kind, detail, heard, text)


HARPER = (
    "Ron Harper (Chicago Bulls), before tonight (1997-10-31 to 1998-06-13, 102 games): made 346 of "
    "783 (44%). Tonight so far: 3 of 4 attempts. Chance now, before tonight and tonight combined: "
    "53%."
)
SON = (
    "Son Heung-Min tonight, in the key moments so far: Shot (Blocked) x2, Shot (Off T) x1, Shot "
    "(Goal) x1"
)
CHICAGO = (
    "Chicago Bulls tonight, in the key moments so far: Field goal (2 points) x10, Field goal "
    "(3 points) x2, Free throw (1 point) x3"
)
RUN = (
    "Momentum, the last 6 key moments from period 3, 01:11: Los Angeles Lakers 6; the score went "
    "from 87-85 to 108-96 (home-away)"
)
RAUF = "Haris Rauf tonight, in the key moments so far: Six (6 runs) x1, Last ball (2 runs) x1"
MALONE = "Karl Malone this season before tonight: made 967 of 1873 shots (52%) in 100 games."

# right lines the check flagged before it added up a stat, read "1,873" or "ten two-pointers"
RIGHT = [
    (BULLS, 24, "player profile", HARPER, "He's shooting 75 percent tonight, three for four."),
    ("3754092", 17, "tally", SON, "Son has four shots tonight: two blocked, one off target."),
    (BULLS, 22, "player profile", MALONE, "Malone came in at 52 percent, 967 of 1,873."),
    (BULLS, 24, "tally", CHICAGO, "Chicago: ten two-pointers, two threes, three free throws."),
    (KOBE, 14, "momentum", RUN, "Turning 87-85 into 108-96. That's a 21-11 run."),
    (ASIA, 27, "tally", RAUF, "Haris Rauf: one six for 6 runs, and 2 runs off the last ball."),
    (ASIA, 12, "tally", IFTIKHAR, "Four sixes and two fours, 32 runs and six boundaries."),
]


@pytest.mark.parametrize(("match_id", "idx", "kind", "detail", "text"), RIGHT)
def test_a_number_the_stat_adds_up_to_passes(match_id, idx, kind, detail, text):
    assert check(match_id, idx, kind, detail, "", text) == []


WRONG_LINE = "Kobe Bryant with another bucket, nine hundred and ninety-nine points now."


def test_a_wrong_analyst_line_is_said_again_once_then_dropped(tmp_path):
    asked = []

    def calls(moment, history):
        if moment["type"] != "Stat":
            return commentator.commentate(moment, history, provider=Fake())
        asked.append(moment["idx"])
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": WRONG_LINE}

    lines, _ = replay(KOBE, Store(tmp_path), calls=calls)
    assert asked and not any(gap(ln) for ln in lines)  # never said
    assert set(Counter(asked).values()) == {2}  # one try, one retry, then the stretch ends


def test_a_right_retry_is_said_and_marked(tmp_path):
    tries = []

    def calls(moment, history):
        if moment["type"] != "Stat":
            return commentator.commentate(moment, history, provider=Fake())
        tries.append(moment["idx"])
        text = WRONG_LINE if len(tries) % 2 else f"Kobe Bryant again {letters(len(tries))}."
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": text}

    lines, _ = replay(KOBE, Store(tmp_path), calls=calls)
    said = [ln for ln in lines if gap(ln)]
    assert said and all(ln["checked"] and ln["retried"] for ln in said)
    assert WRONG_LINE not in [ln["text"] for ln in said]


def test_a_wrong_stored_line_is_made_again_never_replayed(tmp_path, monkeypatch):
    store = Store(tmp_path)

    def wrong_first(moment, history):
        if moment["type"] != "Stat":
            return commentator.commentate(moment, history, provider=Fake())
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": WRONG_LINE}

    monkeypatch.setattr(insight, "wrong_numbers", lambda *a, **k: [])  # stored before the check
    replay(KOBE, store, calls=wrong_first)
    assert WRONG_LINE in [ln["text"] for ln in store.all("lines")]
    monkeypatch.undo()
    fake = Fake()
    lines, _ = replay(KOBE, store, calls=functools.partial(commentator.commentate, provider=fake))
    assert any(gap(ln) for ln in lines) and WRONG_LINE not in [ln["text"] for ln in lines]


ASKED = "How many points does Kobe have, and how many three pointers has he made?"
SAID = "Kobe's up to {} points tonight with that three, and he's made four threes so far."


def test_a_prod_ask_answer_passes_and_a_wrong_count_in_it_is_caught():
    past = [m for m in load_moments(KOBE) if m["idx"] <= 6]
    assert insight.wrong_answer({"text": SAID.format(47)}, ASKED, past, []) == []
    assert insight.wrong_answer({"text": SAID.format("fifty-one")}, ASKED, past, [])
    wilt = "How many points does Kobe have right now, and how many more to pass Wilt's 100?"
    said = {"text": "Kobe's at 43 points tonight, so he'd need 57 more to match Wilt's 100."}
    assert insight.wrong_answer(said, wilt, [m for m in past if m["idx"] <= 5], []) == []


def test_a_wrong_answer_is_asked_again_once_then_off_air(tmp_path):
    from tests.test_core_ask import finished_replay, setup

    asked = []

    def ask(question, past, lines, texts=("So far, Reds 9, Blues 0.",), wrong=()):
        asked.append(question)
        text = texts[min(len(asked), len(texts)) - 1]
        return {"line_id": uuid.uuid4().hex, "moment_idx": past[-1]["idx"], "text": text}

    client, store = setup(tmp_path, ask)
    with client:
        rid = finished_replay(client)
        said = client.post(f"/replays/{rid}/ask", json={"question": "Score?", "moment_idx": 1})
    assert said.json()["off_air"] and len(asked) == 2 and store.all("answers") == []
    asked.clear()
    client, store = setup(tmp_path / "b", functools.partial(ask, texts=("Reds 9.", "Reds 1.")))
    with client:
        rid = finished_replay(client)
        said = client.post(f"/replays/{rid}/ask", json={"question": "Score?", "moment_idx": 1})
    assert said.json()["text"] == "Reds 1." and said.json()["retried"] and len(asked) == 2


def test_ten_two_pointers_is_ten_of_them():
    assert insight.said("ten two-pointers") == [10.0, 2.0, "pointers"]
    assert insight.said("ninety-six, one oh-four") == [96.0, 104.0]


def test_a_retry_never_passes_the_call_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(insight, "MAX_CALLS", 3)
    asked = []

    def calls(moment, history):
        if moment["type"] != "Stat":
            return commentator.commentate(moment, history, provider=Fake())
        asked.append(moment["idx"])
        return {"line_id": uuid.uuid4().hex, "moment_idx": moment["idx"], "text": WRONG_LINE}

    replay(KOBE, Store(tmp_path), calls=calls)
    assert len(asked) == 3  # the third call's retry would be the fourth


@pytest.mark.parametrize("match_id", ["3869685", "3913122"])
def test_every_orientation_line_passes_the_analyst_check(match_id, tmp_path):
    """A stretch opens on where the ball is (#205); its clock and score must not drop it."""
    from data.matches import balls, orientation

    moments, header, found = load_moments(match_id), match_header(match_id), balls(match_id)
    gaps, said = insight.Gaps(match_id, Store(tmp_path)), 0
    for i, m in enumerate(moments):
        if not (b := found.get(m["idx"])):
            continue
        text = orientation(header, moments[: i + 1], b)
        said_as = {"kind": "orientation", "detail": text, "heard": "", "clock": b["clock"]}
        stat = insight.stat_moment(m, said_as, False)
        minute = int(b["clock"].split(":")[0]) + 1  # "in the 23rd minute" of a 22:10 clock
        for line in (text, f"{minute} minutes played. {text}"):
            assert gaps.wrong(line, stat, moments[: i + 1]) == [], line
        said += 1
    assert said >= 10
