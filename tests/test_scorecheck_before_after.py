"""The before/after script asks the frozen Score check request, and its fixed line is wrong."""

import importlib.util
from pathlib import Path

import pytest

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


class Stub:
    record = False

    def __init__(self, answer='{"score":"not_said"}'):
        self.answer = answer
        self.calls = []

    def call(self, request):
        self.calls.append(request)
        return {"content": [{"type": "text", "text": self.answer}]}


def picked(line):
    return "9636", 9, line


def test_f1_is_rejected_before_the_provider_call(monkeypatch):
    provider = Stub()
    monkeypatch.setattr(ba, "default_provider", lambda: provider)
    monkeypatch.setattr(ba, "pick", lambda case, line_id: picked("Safety car deployed"))

    with pytest.raises(SystemExit, match="does not support f1"):
        ba.run("before", "cahill", "offline-line-id")

    assert provider.calls == []


def test_missing_canonical_label_is_rejected_before_the_provider_call(monkeypatch):
    provider = Stub()
    monkeypatch.setattr(ba, "default_provider", lambda: provider)
    monkeypatch.setattr(ba, "pick", lambda case, line_id: ("3754092", 26, "unlabelable"))
    monkeypatch.setattr(ba, "gold", lambda *args: None)

    with pytest.raises(SystemExit, match="no canonical score label"):
        ba.run("before", "cahill", "offline-line-id")

    assert provider.calls == []


def test_not_said_is_a_valid_canonical_label(monkeypatch):
    provider = Stub()
    monkeypatch.setattr(ba, "default_provider", lambda: provider)
    monkeypatch.setattr(ba, "pick", lambda case, line_id: ("3754092", 26, "no score claim"))
    monkeypatch.setattr(ba, "gold", lambda *args: {"score": "not_said"})

    result = ba.run("before", "cahill", "offline-line-id")

    assert len(provider.calls) == 1
    assert result["key"] == "not_said"
    assert result["key_judges"] == "Score check judges only the score's numbers, not who leads"
    assert result["label_parsed"] == "not_said"
    assert result["matches_key"] is True
