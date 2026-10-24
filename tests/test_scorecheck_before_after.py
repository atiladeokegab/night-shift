"""The before/after script asks the frozen Score check request, and its fixed line is wrong."""

import importlib.util
from pathlib import Path

from agent import scorecheck
from data.matches import load_moments, match_header
from eval.linecheck import gold

SPEC = importlib.util.spec_from_file_location(
    "ba", Path(__file__).parent.parent / "scripts" / "scorecheck_before_after.py"
)
ba = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ba)


def test_each_case_is_in_the_frozen_request_with_its_key():
    keys = {}
    for name, (match, idx, line) in ba.CASES.items():
        header, moments = match_header(match), load_moments(match)
        i = next(i for i, m in enumerate(moments) if m["idx"] == idx)
        keys[name] = gold(header, moments[i], moments[:i], line)["score"]
        req = scorecheck.build_request(header, moments[i], line)
        assert req["system"] == scorecheck.SYSTEM and line in req["messages"][0]["content"]
    assert keys["cahill"] == "wrong"  # "lead one-nil" at 1-2
    assert keys["jordan"] == keys["kohli"] == "ok"  # the ledger's gold for both
