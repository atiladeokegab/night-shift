"""The Ask eval (#319): a judge's counts are in the message, own goals add up, and a right answer
gets through the route's path and its check."""

from agent.commentator import FakeProvider, _strangers, answer
from data.matches import load_moments, match_header
from eval.ask_eval import QUESTIONS, ask, verdict


def asked(match_id: str, idx: int) -> str:
    provider = FakeProvider()
    answer("How's it going?", load_moments(match_id)[: idx + 1], [], provider=provider)
    return provider.requests[0]["messages"][0]["content"]


class Says:
    """A model that replies with each scripted content list in turn."""

    def __init__(self, *contents):
        self.contents = list(contents)

    def call(self, request):
        content = self.contents.pop(0)
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        usage = {"input_tokens": 1, "output_tokens": 1}
        return {"content": content, "usage": usage, "request_id": "r"}


def said_to(match_id: str, idx: int, *replies) -> dict:
    return answer("Asked?", load_moments(match_id)[: idx + 1], [], provider=Says(*replies))


def test_an_answer_drops_the_question_said_back():
    # #332: the keyed run said "How much time remains in this final?" and nothing else
    long = "We're at 87 minutes and level at two-two, with three minutes of normal time left"
    said = said_to("3869685", 30, f"How much time remains in this final? {long}, what a final!")
    assert said["text"] == f"{long}, what a final!" and "fallback" not in said


def test_a_first_person_decline_is_said_not_dropped():
    # #332: "I don't ..." went as preamble, leaving nothing, and the viewer heard off air
    decline = "I don't see Megan Rapinoe in this match. The Courage lead three-two."
    assert said_to("7457", 30, decline)["text"] == decline
    later = said_to("3754092", 26, "I can't tell you what comes later, but Spurs lead two-one.")
    assert later["text"] == "I can't tell you what comes later, but Spurs lead two-one."


def test_a_long_answer_sentence_is_cut_at_a_clause_not_dropped():
    # #340: keyed #29 fell back although the Courage's 18 shots were in the message
    long = (
        "They have had eighteen shots so far, absolutely dominating the play here in the first half"
        " while Orlando Pride have struggled badly to find any rhythm at all going forward tonight!"
    )
    said = said_to("7457", 20, f"How many shots have the Courage had? {long}")
    assert said["text"] == "They have had eighteen shots so far!" and "fallback" not in said


def test_a_long_answer_keeps_its_longest_opening_not_its_first_sentence_alone():
    # #349: keyed #2 named only Di María and #21 said only "The Lakers are winning!": the first
    # sentence of a longer reply. The opening up to the last clause that fits is kept instead.
    lakers = (
        "The Lakers are winning! Kobe Bryant has just slammed down a dunk, his fifty-first point,"
        " to give Los Angeles an 87-85 lead with just over a minute left in the third quarter."
    )
    assert said_to("0020500591", 9, lakers)["text"] == (
        "The Lakers are winning! Kobe Bryant has just slammed down a dunk, his fifty-first point."
    )
    argentina = (
        "Ángel Di María has just made it two for Argentina with a finish from the left, after"
        " Lionel Messi's penalty in the twenty-third minute, and Argentina are cruising here"
        " in Lusail!"
    )
    assert said_to("3869685", 9, argentina)["text"] == (
        "Ángel Di María has just made it two for Argentina with a finish from the left, after"
        " Lionel Messi's penalty in the twenty-third minute!"
    )


def test_an_answer_with_nothing_to_say_gives_the_status_not_off_air():
    tool = [{"type": "tool_use", "id": "t1", "name": "get_score", "input": {}}]
    for replies in (["I have all the information I need."], ["How long is left?"], [tool, tool]):
        said = said_to("3754092", 26, *replies)
        assert said["fallback"] and said["text"].startswith("No word on that yet. "), replies
        assert "Tottenham Hotspur lead 2-1" in said["text"]
    assert said_to("3754092", 26, "Let me check.")["tried"] == "Let me check."  # kept to read


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

    def keyed(question: str, idx: int) -> dict:
        return next(q for q in QUESTIONS if (q["q"], q["idx"]) == (question, idx))

    # #332: true answers to the question asked, from the keyed run
    said = "Kylian Mbappé has just scored his second goal of the match!"
    assert verdict(said, keyed("What just happened?", 26)) == "correct"
    said = "Mbappé has just scored again! The France striker fired in a volley from 18 yards!"
    assert verdict(said, keyed("What just happened?", 26)) == "correct"  # #354
    said = "We'll find out who lifts the trophy when this match finishes."
    assert verdict(said, keyed("Who wins the World Cup?", 26)) == "correct"
    said = "The last goal in this match was an own goal!"
    assert verdict(said, keyed("Who scored the last goal?", 42)) == "correct"
    # #349: the run after #343
    said = (
        "We're in the final stretch here at two-two, with just over a minute to play in the ninety!"
    )
    assert verdict(said, keyed("How much time is left?", 40)) == "correct"
    assert verdict("The Lakers are winning!", keyed("Who's winning?", 9)) == "correct"
    assert verdict("The Raptors lead, the Lakers trail.", keyed("Who's winning?", 9)) == "wrong"
    said = "Kobe Bryant just hit his 67th point of the night with that three-pointer!"
    assert verdict(said, keyed("How many points does Kobe have?", 14)) == "correct"
    said = (
        "The Courage have had 18 shots, with Merritt Mathias just finding the net to make it 1-0!"
    )
    assert verdict(said, keyed("How many shots have the Courage had?", 20)) == "wrong"
    said = (
        "Ángel Di María has just made it two for Argentina with a brilliant finish from the left!"
    )
    assert verdict(said, keyed("Who scored for Argentina?", 9)) == "wrong"  # Messi left out
    said = "How much time remains in this final?"  # the echo stays wrong
    assert verdict(said, keyed("How long is left?", 30)) == "wrong"


def test_a_name_not_in_the_match_is_named_in_the_message():
    # #332: the keyed run dodged Neymar and LeBron James; it is told they are not in the match
    provider = FakeProvider()
    answer("Has Neymar scored? Or Mbappe?", load_moments("3869685")[:46], [], provider=provider)
    said = provider.requests[0]["messages"][0]["content"]
    assert 'so say plainly they are not in it: "Neymar"\n' in said
    kobe = match_header("0020500591")
    assert _strangers("How many points has LeBron James scored?", kobe, []) == ["LeBron James"]
    for q in ("How many points does Kobe have?", "Are the Raptors winning?", "What's the score?"):
        assert _strangers(q, kobe, []) == [], q
    spurs = match_header("3754092")  # a nickname or a surname alone is no stranger
    assert _strangers("Are Spurs winning? Has Son scored?", spurs, []) == []
    assert _strangers("Did Frank Lampard score?", spurs, []) == ["Frank Lampard"]


def test_the_games_own_words_are_no_strangers():
    # #336: a judge will ask about "the Final"; a game word or a date must not be called a player
    final = match_header("3869685")
    assert _strangers("Who scored in the World Cup Final?", final, []) == []
    assert _strangers("Is Neymar playing?", final, []) == ["Neymar"]
    spurs = match_header("3754092")  # a Premier League game: Final is still no player
    for q in (
        "Who scored in the Final?",
        "Was there a Penalty in Extra Time?",
        "Any VAR checks before Half-time?",
        "Did the MVP score on Monday in May?",
        "Please, who leads the League?",
    ):
        assert _strangers(q, spurs, []) == [], q
