"""The Ask eval (#319): a judge's counts are in the message, own goals add up, and a right answer
gets through the route's path and its check."""

from agent.commentator import FakeProvider, answer
from data.matches import load_moments
from eval.ask_eval import QUESTIONS, ask, verdict


def asked(match_id: str, idx: int) -> str:
    provider = FakeProvider()
    answer("How's it going?", load_moments(match_id)[: idx + 1], [], provider=provider)
    return provider.requests[0]["messages"][0]["content"]


def test_a_football_ask_holds_each_sides_shots_cards_and_each_scorers_goals():
    said = asked("3754092", 45)  # Chelsea v Tottenham, the last yellow card
    assert "Shots so far (not shootout kicks): Chelsea 13, Tottenham Hotspur 16" in said
    assert "Cards so far: Chelsea 3 yellow cards; Tottenham Hotspur 9 yellow cards" in said
    final = asked("3869685", 62)  # the shootout: its kicks are not shots or goals
    assert "Shots so far (not shootout kicks): Argentina 20, France 10" in final
    assert "Lionel Messi 2 goals, Ángel Di María 1 goal, Kylian Mbappé 3 goals" in final


def test_an_own_goal_is_in_the_goals_so_the_score_adds_up():
    said = asked("7457", 43)  # full time, 3-4: the own goal is out of the recent play
    assert "- 89:13 Poliana (Orlando Pride), own goal for North Carolina Courage" in said
    goals = said.split("Goals so far:\n")[1].split("\nShots")[0].splitlines()
    assert len(goals) == 3 + 4


def test_a_basketball_ask_holds_points_so_far_and_the_clock_as_time_left():
    said = asked("0020500591", 21)  # Vujacic's steal: Kobe's 79 was three moments back
    assert "Clock: Fourth quarter, 1:11 left" in said
    assert "Kobe Bryant 79 (Fourth quarter, 1:47 left); Smush Parker 11" in said


def test_a_right_answer_gets_through_and_every_fact_is_in_the_message():
    for q in QUESTIONS:
        r = ask(q, "gold")
        assert (r["verdict"], r["fallback"]) == ("correct", False), (q["q"], r["text"])
        assert r["in_message"] in (True, "n/a"), q["q"]


def test_the_verdicts():
    q = next(q for q in QUESTIONS if q["q"] == "Has Neymar scored?")
    assert verdict("Neymar has scored twice!", q) == "wrong"
    assert verdict("No, Neymar isn't in this match.", q) == "correct"
    q = next(q for q in QUESTIONS if q["q"] == "How many shots have France had?")
    assert verdict("France have had six shots.", q) == "wrong"
    assert verdict("I can't say, but it's 2-2.", q) == "refused"
    assert verdict("Commentator is off air for a moment", q) == "refused"
