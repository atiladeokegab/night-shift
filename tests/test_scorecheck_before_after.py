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


def test_the_fixed_line_is_a_wrong_score_in_the_frozen_request():
    header, moments = match_header(ba.MATCH), load_moments(ba.MATCH)
    i = next(i for i, m in enumerate(moments) if m["idx"] == ba.IDX)
    assert gold(header, moments[i], moments[:i], ba.LINE)["score"] == ba.KEY == "wrong"
    req = scorecheck.build_request(header, moments[i], ba.LINE)
    assert req["system"] == scorecheck.SYSTEM
    assert "Score: Chelsea 1, Tottenham Hotspur 2" in req["messages"][0]["content"]
