"""Every agent reads the SurrealDB graph (#374): graph facts inside the existing tools' results and
the analyst's facts, the packs as fallback, and Mubit's tool files untouched."""

import hashlib
from pathlib import Path

from agent.commentator import run_tool
from core import graph, insight, predict
from data.matches import load_moments, match_header

KOBE = "0020500591"
AGENT = Path(__file__).resolve().parents[1] / "agent"

# Mubit groups calls into a task by system prompt, tools, output format and model: a change to the
# tools starts a new task, so they change only on purpose (and this pin with them).
PINNED = {
    "tools.json": "a08ff3069c2380654a1f965e5a6011a0b1aaf77c5cf9d70e81ccae461290e2f1",
    "ask_tools.json": "694778819daf4e105f886bc1ce5d4e96b304e291c46cd76a867304ae0c541ba0",
}

SEASON = {
    "team": "Los Angeles Lakers",
    "competition": "NBA",
    "season": "2005-06",
    "matches": 40,
    "totals": {"points": 1400, "rebounds": 210},
}
FORM = [{"date": "2006-01-20", "opponent": "Sacramento Kings", "home": True, "score": "109-98"}]
FORM[0]["result"] = "W"
H2H = [{"date": "2005-12-04", "opponent": "Toronto Raptors", "home": False, "score": "99-102"}]
H2H[0]["result"] = "L"


def test_the_tool_files_that_set_the_mubit_task_are_byte_identical():
    assert {n: hashlib.sha256((AGENT / n).read_bytes()).hexdigest() for n in PINNED} == PINNED


def _profile(monkeypatch, season):
    calls = []

    def player_season(sport, name, before):
        calls.append((sport, name, before))
        return season

    monkeypatch.setattr(graph, "player_season", player_season, raising=False)
    header, past = match_header(KOBE), load_moments(KOBE)[:5]
    return run_tool("get_player_profile", {"name": "kobe"}, header, past), calls


def test_the_profile_tool_adds_the_players_season_from_the_graph(monkeypatch):
    plain, _ = _profile(monkeypatch, None)
    said, calls = _profile(monkeypatch, SEASON)
    assert calls == [("basketball", "Kobe Bryant", "2006-01-22")]  # cut at the match's start
    assert said.startswith(plain + "\n")
    assert said.endswith(
        "Kobe Bryant, NBA 2005-06 before this match: 40 matches, 1400 points, 210 rebounds."
    )


def test_the_profile_tool_is_unchanged_when_the_graph_has_nothing(monkeypatch):
    monkeypatch.delattr(graph, "player_season", raising=False)
    without = run_tool(
        "get_player_profile", {"name": "kobe"}, match_header(KOBE), load_moments(KOBE)[:5]
    )
    assert _profile(monkeypatch, None)[0] == without and "before this match" not in without


def test_the_analyst_gets_each_teams_form_and_their_meetings(monkeypatch):
    seen = []
    monkeypatch.setattr(graph, "team_form", lambda *a, n=5: seen.append(a) or FORM, raising=False)
    monkeypatch.setattr(graph, "head_to_head", lambda *a, n=5: seen.append(a) or H2H, raising=False)
    got = insight._form({}, load_moments(KOBE)[:5])
    assert seen == [
        ("basketball", "Los Angeles Lakers", "2006-01-22"),
        ("basketball", "Toronto Raptors", "2006-01-22"),
        ("basketball", "Los Angeles Lakers", "Toronto Raptors", "2006-01-22"),
    ]
    assert got[0] == (
        "Los Angeles Lakers, the last 1 before this match: 2006-01-20 W 109-98 v Sacramento Kings."
    )
    assert got[2] == (
        "Los Angeles Lakers against Toronto Raptors before this match: "
        "2005-12-04 L 99-102 at Toronto Raptors."
    )


def test_no_graph_form_means_no_form_fact(monkeypatch):
    monkeypatch.setattr(graph, "team_form", lambda *a, n=5: [], raising=False)
    monkeypatch.setattr(graph, "head_to_head", lambda *a, n=5: None, raising=False)
    assert insight._form({}, load_moments(KOBE)[:5]) == []


def test_the_graphs_pack_comes_first_and_keeps_what_only_the_file_has(monkeypatch):
    file = predict.load_pack("basketball", KOBE)
    monkeypatch.setattr(graph, "pack", lambda mid: None)
    assert predict.pack("basketball", KOBE) == file
    monkeypatch.setattr(
        graph, "pack", lambda mid: {"match_id": mid, "players": {"Kobe Bryant": {"games": 99}}}
    )
    got = predict.pack("basketball", KOBE)
    assert got["source"] == file["source"] and got["players"].keys() == file["players"].keys()
    assert got["players"]["Kobe Bryant"] == {**file["players"]["Kobe Bryant"], "games": 99}
