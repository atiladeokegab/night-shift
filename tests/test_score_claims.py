"""A current score remains a claim after an unrelated negative or historical clause."""

import pytest

from core import insight
from data.matches import load_moments, match_header

MATCH = "3754092"
MOMENTS = load_moments(MATCH)
MOMENT = next(m for m in MOMENTS if m["idx"] == 28)  # Chelsea 1–2 Tottenham
PAST = [m for m in MOMENTS if m["idx"] < MOMENT["idx"]]
HEADER = match_header(MATCH)


@pytest.mark.parametrize(
    "text",
    [
        "Not long left and Tottenham lead one-nil.",
        "Tottenham were dominant and still lead one-nil.",
        "Tottenham have not stopped attacking but lead one-nil.",
        "Chelsea need a goal but Tottenham lead one-nil.",
        "Tottenham lead one—nil.",
    ],
)
def test_a_wrong_current_score_is_caught(text):
    assert any("not the score" in w for w in insight.wrong_numbers(text, MOMENT, HEADER, PAST))


@pytest.mark.parametrize(
    "text",
    [
        "Not long left and Tottenham lead two-one.",
        "Tottenham were dominant and still lead two-one.",
        "Tottenham have not stopped attacking but lead two-one.",
        "Tottenham lead two—one.",
        "It was one-nil at the break.",
        "It was one-nil and then two-nil at the break.",
        "Tottenham need one-nil to win.",
        "Tottenham will win one-nil.",
        "Tottenham lead two-one, not one-nil.",
        "Is it one-nil?",
    ],
)
def test_true_scores_and_noncurrent_scores_are_not_rejected(text):
    assert insight.wrong_numbers(text, MOMENT, HEADER, PAST) == []


def test_a_spaced_em_dash_does_not_join_a_minute_to_a_count():
    assert insight._wrong_score("It is minute ten — one more chance for Chelsea.", MOMENT) == []
    minute = int(MOMENT["clock"].split(":")[0])
    text = f"It is minute {minute} — one more chance for Chelsea."
    assert insight.wrong_numbers(text, MOMENT, HEADER, PAST) == []


@pytest.mark.parametrize(
    "need",
    ["need", "will need", "would need", "could get", "must get", "want", "hope for", "are chasing"],
)
def test_a_future_score_stays_hypothetical_after_and(need):
    text = f"Chelsea {need} two more goals and they lead three-two."
    assert insight._wrong_score(text, MOMENT) == []


def test_a_missed_current_score_uses_the_existing_retry_and_fallback():
    calls = []

    def commentate(moment, history):
        calls.append(moment)
        return {"text": "Not long left and Tottenham lead one-nil."}

    line = insight.checked(commentate, MOMENT, PAST)
    assert len(calls) == 2
    assert line["fallback"] and line["checked"]
    assert insight.wrong_numbers(line["text"], MOMENT, HEADER, PAST) == []
