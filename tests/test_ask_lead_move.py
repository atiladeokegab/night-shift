"""#389: "What just happened?" on Vujacic's steal (Kobe's 81, moment 21) was answered "Lakers extend
their lead to eighteen points, 120 to 102": the free throws before it, not the steal, and the score
did not move. Ask's check now flags a lead said to move at a moment that scored nothing."""

from core import insight
from data.matches import load_moments

KOBE = "0020500591"
BAD = "What just happened? The Lakers extend their lead to eighteen points, 120 to 102!"
GOOD = "What just happened? Sasha Vujacic steals it from Charlie Villanueva! Lakers lead 120-102."


def asker(*texts: str):
    said = list(texts)

    def ask(question, past, lines, wrong=()):
        ask.wrong.append(list(wrong))
        return {"text": said.pop(0)}

    ask.wrong = []
    return ask


def test_a_lead_said_to_grow_on_the_steal_is_asked_again_and_the_steal_kept():
    past = load_moments(KOBE)[:22]  # up to moment 21, the steal at 120-102
    assert past[-1]["score"] == past[-2]["score"]
    ask = asker(BAD, GOOD)
    got = insight.checked_answer(ask, "What just happened?", past, [])
    assert got["text"] == GOOD and got.get("retried") and not got.get("fallback")
    assert ask.wrong[1] == [
        "the score did not change at this moment (Steal); Los Angeles Lakers lead 120-102"
    ]


def test_a_lead_that_grew_or_may_grow_passes():
    scored = load_moments(KOBE)[:21]  # moment 20: Bryant's free throw makes it 120-102
    assert insight.wrong_lead_move(BAD, scored) == []
    steal = load_moments(KOBE)[:22]
    assert insight.wrong_lead_move("The Lakers could extend their lead here.", steal) == []
    assert insight.wrong_lead_move(GOOD, steal) == []
    assert insight.wrong_lead_move("Toronto are cutting the gap.", steal)
