"""A lead-moving phrase only fails Ask's check when it affirmatively describes this play."""

from core import insight
from data.matches import load_moments

KOBE = "0020500591"
STEAL = load_moments(KOBE)[:22]
BAD = "The Lakers extend their lead to eighteen points on the steal, 120-102."
NEGATED = "The Lakers did not extend their lead on the steal; the score stayed 120-102."
HISTORICAL = "The Lakers had extended their lead earlier; this steal left it 120-102."
MIXED = (
    "The Lakers had extended their lead earlier, but they extend their lead again on this steal."
)


def test_affirmative_current_lead_movement_still_fails():
    assert insight.wrong_lead_move(BAD, STEAL)


def test_negated_current_lead_movement_passes():
    assert insight.wrong_lead_move(NEGATED, STEAL) == []


def test_explicitly_historical_lead_movement_passes():
    assert insight.wrong_lead_move(HISTORICAL, STEAL) == []


def test_historical_clause_does_not_hide_a_false_current_claim():
    assert insight.wrong_lead_move(MIXED, STEAL)


def test_not_only_is_still_an_affirmative_claim():
    assert insight.wrong_lead_move("The Lakers not only extend their lead on the steal.", STEAL)


def test_checked_answer_keeps_correct_negated_claim_without_retry_or_fallback():
    calls = []

    def ask(question, past, lines, wrong=()):
        calls.append(list(wrong))
        return {"text": NEGATED}

    answer = insight.checked_answer(ask, "What happened on the steal?", STEAL, [])

    assert answer["text"] == NEGATED
    assert answer.get("checked") is True
    assert not answer.get("retried") and not answer.get("fallback")
    assert calls == [[]]
