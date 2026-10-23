"""The commentator request, the no-leak rule (S10) and the traffic runner, all offline."""

import json

import pytest

from agent import commentator, feed
from agent.commentator import FakeProvider, build_request, commentate, line_for
from scripts import replay_matches

FOOT = {
    "sport": "football",
    "match_id": "7",
    "home": "Reds",
    "away": "Blues",
    "competition": "Cup",
    "stage": "Final",
    "date": "2020-01-01",
}
CRIC = {
    "sport": "cricket",
    "match_id": "8",
    "home": "A",
    "away": "B",
    "competition": "T20",
    "stage": "",
    "date": "2020-01-02",
}


def moment(header, idx, player="Ann", outcome="Saved", **extra):
    m = {
        "sport": header["sport"],
        "match_id": header["match_id"],
        "idx": idx,
        "period": 1,
        "clock": f"{idx:02d}:00",
        "type": "Shot",
        "team": "Reds",
        "players": {"shooter": player},
        "outcome": outcome,
        "score": {"home": 0, "away": 0},
        "detail": {},
    }
    if header["sport"] == "cricket":
        m.update(
            clock=f"{idx}.1",
            type="Wicket",
            team="A",
            players={"batter": player},
            score={"runs": 10 * idx, "wickets": idx},
            detail={"wicket_kind": "bowled"},
        )
    return {**m, **extra}


class AskEverything(FakeProvider):
    """Calls every tool in the first round, as a curious model might."""

    def call(self, request):
        if len(request["messages"]) == 1:
            self.requests.append(json.loads(json.dumps(request)))
            uses = [
                ("get_score", {}),
                ("get_player", {"name": "Zed"}),
                ("get_recent_play", {"count": 10}),
            ]
            return {
                "content": [
                    {"type": "tool_use", "id": f"t{i}", "name": n, "input": a}
                    for i, (n, a) in enumerate(uses)
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "request_id": "r1",
                "first_word_ms": None,
            }
        return super().call(request)


def test_frozen_parts_are_byte_identical_across_sports():
    f = build_request(FOOT, [moment(FOOT, 0)])
    c = build_request(CRIC, [moment(CRIC, 0)])
    for key in ("model", "max_tokens", "temperature", "system", "tools", "tool_choice"):
        assert json.dumps(f[key]) == json.dumps(c[key])
    assert f["metadata"] == {"user_id": "match-football-7"}
    assert c["metadata"] == {"user_id": "match-cricket-8"}
    # Only the template's fields differ: the template's fixed text is in both messages.
    for fixed in ("Sport: ", "Score after this moment: ", "Recent play:"):
        assert fixed in f["messages"][0]["content"] and fixed in c["messages"][0]["content"]


def test_a_later_event_never_reaches_the_model():
    for header in (FOOT, CRIC):
        moments = [moment(header, i) for i in range(4)]
        moments.append(moment(header, 4, player="Zed FUTURE", outcome="Goal FUTURE"))
        provider = AskEverything()
        line = line_for(header, moments, 2, provider)
        assert len(provider.requests) == 2 and len(line["tool_calls"]) == 3
        assert "FUTURE" not in json.dumps(provider.requests)
        assert "FUTURE" not in json.dumps(line)


def test_one_tool_round_then_a_line():
    moments = [moment(FOOT, 0, outcome="Goal", score={"home": 1, "away": 0})]
    provider = FakeProvider()
    line = line_for(FOOT, moments, 0, provider)
    assert [c["name"] for c in line["tool_calls"]] == ["get_score"]
    assert "Reds 1, Blues 0" in line["tool_calls"][0]["output"]
    assert line["text"] and line["mubit_request_ids"] == ["fake-1", "fake-2"]
    assert set(line) == {
        "line_id",
        "sport",
        "match_id",
        "moment_idx",
        "text",
        "model",
        "latency_ms",
        "first_word_ms",
        "tokens_in",
        "tokens_out",
        "mubit_request_ids",
        "tool_calls",
        "created_at",
    }
    assert line["model"] == commentator.MODEL == "claude-haiku-4-5"


def test_runner_skips_demo_held_out_and_replayed_matches(monkeypatch, tmp_path):
    ids = [3906390, 105, 106, 107, 108]  # demo, held out, then eligible
    monkeypatch.setattr(replay_matches, "FOOTBALL", [(1, 1)])
    monkeypatch.setattr(feed, "statsbomb_matches", lambda c, s: [{"match_id": i} for i in ids])
    monkeypatch.setattr(
        feed,
        "load",
        lambda sport, mid, meta: (
            {**FOOT, "match_id": mid},
            [moment({**FOOT, "match_id": mid}, i) for i in range(3)],
        ),
    )
    out = tmp_path / "lines.jsonl"

    assert replay_matches.main(["--football", "2", "--fake", "--out", str(out)]) == 0
    lines = [json.loads(r) for r in out.read_text().splitlines()]
    assert {line["match_id"] for line in lines} == {"106", "107"}
    assert len(lines) == 6

    replay_matches.main(["--football", "2", "--fake", "--out", str(out)])
    again = [json.loads(r) for r in out.read_text().splitlines()][6:]
    assert {line["match_id"] for line in again} == {"108"}  # never a match already there


def test_pick_keeps_goals_and_spreads_the_rest():
    moments = [moment(FOOT, i, outcome="Goal" if i in (3, 40) else "Saved") for i in range(50)]
    picked = replay_matches.pick(moments, 10)
    assert len(picked) == 10 and {3, 40} <= set(picked) and picked == sorted(set(picked))


def test_server_seam_on_the_bundled_samples(monkeypatch):
    from data.matches import list_matches, load_moments

    monkeypatch.delenv("MUBIT_API_KEY", raising=False)
    monkeypatch.setattr(commentator, "_provider", None)
    samples = list_matches()
    assert {(m["sport"], m["match_id"]) for m in samples} == feed.DEMO
    assert all(m["sample"] for m in samples)
    for m in samples:
        moments = load_moments(m["match_id"])
        line = commentate(moments[3], moments[:3])
        assert line["match_id"] == m["match_id"] and line["moment_idx"] == 3 and line["text"]
    for bad in ("nope", "../sample/cricket-1298150", "*"):
        try:
            load_moments(bad)
            raise AssertionError(bad)
        except KeyError:
            pass


class Scripted:
    """Answers each call with the next scripted content list."""

    def __init__(self, *contents):
        self.contents = list(contents)

    def call(self, request):
        return {
            "content": self.contents.pop(0),
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "request_id": f"r{len(self.contents)}",
            "first_word_ms": 5.0,
        }


TOOL = [{"type": "tool_use", "id": "t1", "name": "get_score", "input": {}}]


def text(t):
    return [{"type": "text", "text": t}]


def test_a_tool_only_last_reply_is_no_line_not_a_blank_one():
    moments = [moment(FOOT, 0)]
    with pytest.raises(commentator.NoLine):
        line_for(FOOT, moments, 0, Scripted(TOOL, TOOL))
    assert commentate(moments[0], [], header=FOOT, provider=Scripted(TOOL, TOOL)) is None


@pytest.mark.parametrize(
    "said",
    [
        "I have all the information I need from your message.",
        "Let me check the score first.",
        "There's a discrepancy here: you say the event is a shot off target. Could you clarify?",
        "",
    ],
)
def test_preamble_alone_is_no_line(said):
    with pytest.raises(commentator.NoLine):
        line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text(said)))


@pytest.mark.parametrize(
    "said",
    [
        "I have all the information I need from your message.\n\nGoal! Ann buries it.",
        "I have all the information I need from your message. Goal! Ann buries it.",
        "Based on the score, here goes: Goal! Ann buries it.",
        "I have all the information I need from your message… Goal! Ann buries it.",
    ],
)
def test_preamble_never_becomes_the_line(said):
    line = line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text(said)))
    assert line["text"] == "Goal! Ann buries it."


def test_a_line_starting_with_now_is_kept():
    line = line_for(FOOT, [moment(FOOT, 0)], 0, Scripted(text("Now that is a strike from Ann!")))
    assert line["text"] == "Now that is a strike from Ann!"


def test_one_untemplated_prompt_asks_for_a_broadcast_call_on_big_moments():
    # A-3.6 offline: the live check (a judge on real lines) is tests/acceptance/test_A_3_6.py.
    system = commentator.SYSTEM
    assert "$" not in system and "{" not in system  # fixed text, never templated per sport
    for sport in ("football", "cricket", "basketball", "formula"):
        assert sport not in system.lower()  # the sport goes in the message, never the prompt
    for rule in ("changes the score, the lead or the result", "emotion", "20 words"):
        assert rule in system
    assert "calmly" in system  # routine moments stay calm
    assert build_request(FOOT, [moment(FOOT, 0)])["temperature"] == 0
