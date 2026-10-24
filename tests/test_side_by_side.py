import json
from pathlib import Path

import pytest

from agent import feed
from agent.commentator import FakeProvider
from eval.side_by_side import NO_LINE, OUT, build
from scripts.replay_matches import eligible

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"
HELD_OUT = "3857272"  # England v United States, 2022: sha256 % 5 == 0


def sample(match_id: str):
    data = json.loads((SAMPLE / "football-3869685.json").read_text(encoding="utf-8"))
    header = {**data["header"], "match_id": match_id}
    return header, [{**m, "match_id": match_id} for m in data["moments"]]


def test_every_recorded_pair_is_held_out_and_never_trained_on():
    report = json.loads(OUT.read_text(encoding="utf-8"))
    assert 3 <= len(report["pairs"]) <= 6
    for pair in report["pairs"]:
        key = (pair["sport"], pair["match_id"])
        assert feed.held_out(*key), key
        assert key not in feed.DEMO, key
        # the traffic runner, the only path that trains the adapter, never sends this match
        assert not eligible(*key, seen=set()), key


def test_recorded_pairs_never_claim_what_was_not_measured():
    report = json.loads(OUT.read_text(encoding="utf-8"))
    assert report["recorded_on"] and report["adapter"]["callable"] is False
    for pair in report["pairs"]:
        assert pair["big"]["text"].strip()
        assert pair["adapter"] is None and pair["verdict"] == NO_LINE


def test_build_offline_records_the_big_line_and_no_adapter_line():
    assert feed.held_out("football", HELD_OUT)
    report = build([sample(HELD_OUT)], FakeProvider(), 4, {"status": "not ready"}, "2026-10-24")
    assert report["recorded_on"] == "2026-10-24"
    assert len(report["pairs"]) == 4
    for pair in report["pairs"]:
        assert pair["match_id"] == HELD_OUT and pair["big"]["text"]
        assert pair["big"]["cost_usd"] > 0 and pair["big"]["latency_ms"] is not None
        assert pair["adapter"] is None and pair["verdict"] == NO_LINE


def test_build_refuses_a_match_that_is_not_held_out():
    with pytest.raises(ValueError):
        build([sample("3869685")], FakeProvider(), 4, {}, "2026-10-24")
