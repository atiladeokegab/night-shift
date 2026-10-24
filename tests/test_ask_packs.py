"""Prediction questions to Ask (#118): a number Ask quotes about a player's record comes from the
pre-match pack, through its tool, or the number check stops it and the viewer never hears it."""

import pytest

from agent.commentator import answer
from core import predict
from core.insight import checked_answer
from data.matches import load_moments, match_header

CASES = [("0020500591", "Kobe"), ("0049700088", "Jordan"), ("3869685", "Messi")]


class Scripted:
    """A model that asks for the player's profile (or not), then says `say(tool output)`."""

    def __init__(self, who, say, use_tool=True):
        self.who, self.say, self.use_tool, self.out = who, say, use_tool, None

    def call(self, request):
        last = request["messages"][-1]["content"]
        if self.use_tool and isinstance(last, str):  # the question: look the player up first
            use = {"type": "tool_use", "id": "t1", "name": "get_player_profile"}
            content = [{**use, "input": {"name": self.who}}]
        else:
            self.out = last[0]["content"] if isinstance(last, list) else ""
            content = [{"type": "text", "text": self.say(self.out)}]
        return {
            "content": content,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "request_id": "r",
        }


def ask_with(match_id, provider):
    past = load_moments(match_id)[:20]
    header = match_header(match_id)

    def ask(question, past, lines, wrong=()):
        return answer(question, past, lines, header=header, provider=provider, wrong=wrong)

    return checked_answer(ask, f"Will {provider.who} score his next shot?", past, []), past


def record(match_id, who):
    pack = predict.load_pack(match_header(match_id)["sport"], match_id)
    p = pack["players"][predict.find(pack, who)]
    return p["made"], p["attempts"]


@pytest.mark.parametrize(("match_id", "who"), CASES)
def test_the_pack_record_is_quoted_through_the_tool_and_passes(match_id, who):
    made, attempts = record(match_id, who)
    said = Scripted(who, lambda out: f"{who}: {made} from {attempts} before tonight.")
    got, _ = ask_with(match_id, said)
    assert f"{made} from {attempts}" in got["text"] and got["checked"]
    assert not got.get("retried") and not got.get("fallback")
    assert f"{made} of {attempts}" in said.out or f"{made} goals from {attempts}" in said.out


@pytest.mark.parametrize(("match_id", "who"), CASES)
def test_a_record_the_pack_does_not_hold_is_never_heard(match_id, who):
    made, attempts = record(match_id, who)
    wrong = attempts + 997  # in no pack field, moment or line
    said = Scripted(who, lambda out: f"{who}: {made} from {wrong} before tonight.")
    got, _ = ask_with(match_id, said)
    assert got["fallback"] and str(wrong) not in got["text"]
    assert f"{wrong} is not in the match so far" in got["wrong"]


def test_the_pack_number_needs_the_pack_tool():
    made, attempts = record("0020500591", "Kobe")
    said = Scripted("Kobe", lambda out: f"Kobe: {attempts} shots before tonight.", use_tool=False)
    got, _ = ask_with("0020500591", said)
    assert got["fallback"]  # can go red: with the tool's output in hand the same answer passes
    assert f"{attempts:g} is not in the match so far" in got["wrong"]
