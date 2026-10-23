"""The commentator request, the no-leak rule (S10) and the traffic runner, all offline."""

import json

from agent import commentator, feed
from agent.commentator import FakeProvider, build_request, commentate
from scripts import replay_matches

FOOT = {"sport": "football", "match_id": "7", "home": "Reds", "away": "Blues",
        "competition": "Cup", "stage": "Final", "date": "2020-01-01"}
CRIC = {"sport": "cricket", "match_id": "8", "home": "A", "away": "B",
        "competition": "T20", "stage": "", "date": "2020-01-02"}


def moment(header, idx, player="Ann", outcome="Saved", **extra):
    m = {"sport": header["sport"], "match_id": header["match_id"], "idx": idx, "period": 1,
         "clock": f"{idx:02d}:00", "type": "Shot", "team": "Reds", "players": {"shooter": player},
         "outcome": outcome, "score": {"home": 0, "away": 0}, "detail": {}}
    if header["sport"] == "cricket":
        m.update(clock=f"{idx}.1", type="Wicket", team="A", players={"batter": player},
                 score={"runs": 10 * idx, "wickets": idx}, detail={"wicket_kind": "bowled"})
    return {**m, **extra}


class AskEverything(FakeProvider):
    """Calls every tool in the first round, as a curious model might."""

    def call(self, request):
        if len(request["messages"]) == 1:
            self.requests.append(json.loads(json.dumps(request)))
            uses = [("get_score", {}), ("get_player", {"name": "Zed"}),
                    ("get_recent_play", {"count": 10})]
            return {"content": [{"type": "tool_use", "id": f"t{i}", "name": n, "input": a}
                                for i, (n, a) in enumerate(uses)],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "request_id": "r1", "first_word_ms": None}
        return super().call(request)


def test_frozen_parts_are_byte_identical_across_sports():
    f = build_request(FOOT, [moment(FOOT, 0)])
    c = build_request(CRIC, [moment(CRIC, 0)])
    for key in ("model", "max_tokens", "system", "tools", "tool_choice"):
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
        line = commentate(header, moments, 2, provider)
        assert len(provider.requests) == 2 and len(line["tool_calls"]) == 3
        assert "FUTURE" not in json.dumps(provider.requests)
        assert "FUTURE" not in json.dumps(line)


def test_one_tool_round_then_a_line():
    moments = [moment(FOOT, 0, outcome="Goal", score={"home": 1, "away": 0})]
    provider = FakeProvider()
    line = commentate(FOOT, moments, 0, provider)
    assert [c["name"] for c in line["tool_calls"]] == ["get_score"]
    assert "Reds 1, Blues 0" in line["tool_calls"][0]["output"]
    assert line["text"] and line["mubit_request_ids"] == ["fake-1", "fake-2"]
    assert set(line) == {"line_id", "sport", "match_id", "moment_idx", "text", "model",
                         "latency_ms", "first_word_ms", "tokens_in", "tokens_out",
                         "mubit_request_ids", "tool_calls", "created_at"}
    assert line["model"] == commentator.MODEL == "claude-haiku-4-5"


def test_runner_skips_demo_held_out_and_replayed_matches(monkeypatch, tmp_path):
    ids = [3906390, 105, 106, 107, 108]  # demo, held out, then eligible
    monkeypatch.setattr(replay_matches, "FOOTBALL", [(1, 1)])
    monkeypatch.setattr(feed, "statsbomb_matches", lambda c, s: [{"match_id": i} for i in ids])
    monkeypatch.setattr(feed, "load", lambda sport, mid, meta: (
        {**FOOT, "match_id": mid}, [moment({**FOOT, "match_id": mid}, i) for i in range(3)]))
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
