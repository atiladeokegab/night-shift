"""Let them watch (#291): a note of the viewer's shared screen goes in the next line's user message,
never the system prompt or tools, so the lead's Mubit task stays the same."""

from agent.commentator import build_request
from data.matches import load_moments, match_header

JAZZ = "0049700088"
NOTE = "a replay of the dunk from behind the basket"


def request_at(idx, seen=None, stat=False):
    moments = load_moments(JAZZ)[: idx + 1]
    if stat:
        moments[-1] = {**moments[-1], "type": "Stat"}
    return build_request(match_header(JAZZ), moments, (), seen)


def test_a_note_goes_at_the_end_of_the_user_message_only():
    for stat in (False, True):
        plain, seen = request_at(33, stat=stat), request_at(33, NOTE, stat)
        said = seen["messages"][0]["content"]
        assert said == plain["messages"][0]["content"] + f"\nOn screen: {NOTE}"
        # byte-identical: the system prompt, tools, model and everything else
        assert {**seen, "messages": None} == {**plain, "messages": None}
        assert NOTE not in seen["system"]


def test_no_note_leaves_the_request_as_it_was():
    assert request_at(33, None) == request_at(33, "") == request_at(33)
