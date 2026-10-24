"""Ask at 105:41 of the World Cup final (#236): prod said "Messi hasn't scored yet... second half
of extra time". The question now sees his penalty and the half, and a wrong answer is never said."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent.commentator import FakeProvider, answer
from core.app import Deps, asked_so_far, create_app
from core.insight import checked_answer, wrong_claims
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments

FINAL, AT = "3869685", 45  # idx 45: Lautaro Martínez off target, 105:41, period 3, 2-2
ASKED = "How did Messi score?"
WRONG = "Messi hasn't scored yet, we're deep in the second half of extra time!"
RIGHT = "How did Messi score? From the spot, sending Lloris the wrong way. Two-all now."


def past_at_105_41():
    moments = load_moments(FINAL)
    replay = SimpleNamespace(events=[{"event": "moment", "data": m} for m in moments])
    past, lines = asked_so_far(replay, moments, AT)
    assert past[-1]["clock"] == "105:41"
    return past, lines


def test_the_question_at_105_41_holds_messis_penalty_and_the_first_half_of_extra_time():
    past, lines = past_at_105_41()
    provider = FakeProvider()
    answer(ASKED, past, lines, provider=provider)
    asked = provider.requests[0]["messages"][0]["content"]
    assert "22:24 Lionel Messi (Argentina), penalty" in asked
    assert "Part of the match: first half of extra time" in asked


def test_messi_has_not_scored_is_caught_and_the_half_too():
    past, _ = past_at_105_41()
    assert wrong_claims(WRONG, past) == [
        "the match has not reached the second half of extra time",
        "Lionel Messi has scored 1 so far",
    ]
    assert wrong_claims(RIGHT, past) == []
    assert wrong_claims("Mbappé has his brace; Messi his second!", past) == [
        "Lionel Messi has scored 1 so far, not 2"
    ]
    assert wrong_claims("Mbappé completes a hat-trick!", past) == [
        "Kylian Mbappé has scored 2 so far, not 3"
    ]
    assert wrong_claims("Messi scored, but Di María hasn't scored.", past) == [
        "Ángel Di María has scored 1 so far"
    ]


# false at 105:41, caught by 553c47c and let through by 211f2ef's wide exemption: each is caught
WRONG_AT_105_41 = [
    "Messi hasn't scored in this final.",
    "Messi has yet to score in this match.",
    "Messi hasn't scored yet in the final.",
    "No goal for Messi yet.",
]


def test_messi_has_not_scored_in_this_final_is_caught():
    past, _ = past_at_105_41()
    for text in WRONG_AT_105_41:
        assert wrong_claims(text, past) == ["Lionel Messi has scored 1 so far"], text


# "no goal for <player>" after #254 (Prometheus, review-b): the player it is for, by full name too,
# over anyone named earlier
MESSI = "Lionel Messi has scored 1 so far"
WRONG_FOR_AT_105_41 = [
    ("No goal for Lionel Messi yet.", MESSI),
    ("No goals for Kylian Mbappé yet.", "Kylian Mbappé has scored 2 so far"),
    ("No goal for Ángel Di María yet.", "Ángel Di María has scored 1 so far"),
    ("Lautaro Martínez is searching, but no goal for Messi yet.", MESSI),
    ("No goal yet for Messi.", MESSI),
    ("Mbappé has two, but no goal for Messi yet.", MESSI),
]


def test_no_goal_for_a_player_is_that_players_claim():
    past, _ = past_at_105_41()
    for text, reason in WRONG_FOR_AT_105_41:
        assert wrong_claims(text, past) == [reason], text


# true answers review-b found flagged (#247): each must pass
TRUE_AT_105_41 = [
    "Mbappé is one away from a hat-trick.",
    "Mbappé has not scored since the 81st minute.",
    "Messi hasn't scored in extra time yet.",
    "Messi's penalty was not the only goal.",
    "Messi scored, but Di María has not scored since the first half.",
    "Messi hasn't scored again since his penalty.",
    "Messi hasn't scored again.",
    "Messi hasn't scored from open play.",
    "Mbappé has two; no goal for Messi in extra time.",
    "No goals for France in extra time, but Mbappé has two.",
    "No goal yet for Messi in extra time.",
    "No goal for Ángel Di María in extra time.",
]


# "for <team>" is nobody's claim, even with Messi's penalty in (review-b, Prometheus on #265)
FOR_A_TEAM_AT_31_35 = [
    "Messi scored from the spot, but no goal for France yet.",
    "No goals for France while Messi has scored.",
    "No goal for France but Messi has scored.",
]


def test_true_claims_about_goals_and_halves_are_not_flagged():
    past, _ = past_at_105_41()
    for text in TRUE_AT_105_41:
        assert wrong_claims(text, past) == [], text
    at_31_35 = [m for m in load_moments(FINAL) if m["idx"] <= 8]
    assert at_31_35[-1]["clock"] == "31:35"
    assert wrong_claims("France need to come out stronger in the second half.", at_31_35) == []
    for text in FOR_A_TEAM_AT_31_35:
        assert wrong_claims(text, at_31_35) == [], text
    assert wrong_claims("We're now in the second half.", at_31_35) == [
        "the match has not reached the second half"
    ]


def model(*texts):
    asked = []

    def ask(question, past, lines, wrong=()):
        asked.append(list(wrong))
        return {"line_id": "a1", "moment_idx": past[-1]["idx"], "text": texts[len(asked) - 1]}

    return ask, asked


def test_a_wrong_answer_is_asked_again_with_the_reasons():
    past, lines = past_at_105_41()
    ask, asked = model(WRONG, RIGHT)
    said = checked_answer(ask, ASKED, past, lines)
    assert said["text"] == RIGHT and said["retried"]
    assert asked[0] == [] and "Lionel Messi has scored 1 so far" in asked[1]


def test_wrong_twice_at_105_41_says_the_data_and_never_publishes_the_wrong_line(tmp_path):
    ask, asked = model(WRONG, WRONG)

    def line(m, history):
        return {"line_id": f"l{m['idx']}", "match_id": FINAL, "moment_idx": m["idx"], "text": ""}

    store = Store(tmp_path)
    deps = Deps(list_matches, load_moments, line, ask=ask)
    with TestClient(create_app(store=store, deps=deps)) as client:
        rid = client.post("/replays", json={"match_id": FINAL, "speed": 1e6}).json()["replay_id"]
        read_stream(client, rid)
        said = client.post(f"/replays/{rid}/ask", json={"question": ASKED, "moment_idx": AT})
    reply = said.json()
    assert len(asked) == 2 and reply["fallback"] and reply["tried"] == WRONG
    assert reply["text"].startswith("Extra time, 105 minutes played.")
    assert "Lionel Messi after 22 minutes" in reply["text"]
    assert [a["text"] for a in store.all("answers")] == [reply["text"]]


# "he" in an Ask answer is the player named last in the answer, else in the question
HE_WRONG = [
    (ASKED, "He hasn't scored yet.", "Lionel Messi has scored 1 so far"),
    ("", "Messi was brilliant. He hasn't scored yet, though.", "Lionel Messi has scored 1 so far"),
    ("Has Mbappé scored?", "He is yet to score.", "Kylian Mbappé has scored 2 so far"),
    (ASKED, "He's still yet to score!", "Lionel Messi has scored 1 so far"),
    # any case, and the claim is the real player's (Prometheus on #264)
    ("how did messi score?", "He has not scored yet.", "Lionel Messi has scored 1 so far"),
    ("HOW DID KYLIAN MBAPPÉ SCORE?", "He hasn't scored yet.", "Kylian Mbappé has scored 2 so far"),
    ("", "No goal for ángel di maría yet.", "Ángel Di María has scored 1 so far"),
]
HE_RIGHT = [
    (ASKED, "Lautaro Martínez went close. He hasn't scored yet."),  # the answer's name wins
    (ASKED, "He hasn't scored since his penalty."),
    (ASKED, "He hasn't scored again."),
    (ASKED, "Then he hasn't scored in extra time."),
    ("Has Montiel scored?", "He hasn't scored yet."),
    ("Where are we?", "He hasn't scored yet."),  # no one named: no one to check
    ("Messi scored; has lautaro martínez scored?", "He hasn't scored yet."),
]


def test_he_hasnt_scored_is_the_player_named_last_in_the_answer_or_question():
    past, _ = past_at_105_41()
    for question, text, reason in HE_WRONG:
        assert wrong_claims(text, past, question) == [reason], text
    for question, text in HE_RIGHT:
        assert wrong_claims(text, past, question) == [], text


def test_a_he_answer_is_retried_with_the_question_s_player():
    past, lines = past_at_105_41()
    ask, asked = model("He hasn't scored yet.", RIGHT)
    assert checked_answer(ask, ASKED, past, lines)["text"] == RIGHT
    assert "Lionel Messi has scored 1 so far" in asked[1]
