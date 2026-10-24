"""The competition store behind the graph contract (#373): small fixture graph, the cut at kickoff,
and the fallback to the packs when the engine fails."""

import logging

import pytest

from core import graph
from scripts import build_graph


def fx(mid, start, home, away, hg, ag, season="2015/2016"):
    return {"sport": "football", "mid": mid, "competition": "PL", "season": season,
            "start": start, "home": home, "away": away, "hg": hg, "ag": ag}  # fmt: skip


def ap(mid, start, player, team, goals, season="2015/2016"):
    return {"sport": "football", "mid": mid, "player": player, "team": team, "start": start,
            "competition": "PL", "season": season, "minutes": 90,
            "totals": {"goals": goals, "shots": goals + 1, "xg": 0.5, "assists": 0}}  # fmt: skip


FIXTURES = [
    fx("1", "2015-08-08T15:00:00", "Chelsea", "Spurs", 2, 1),
    fx("2", "2015-09-01T15:00:00", "Spurs", "Chelsea", 0, 0),
    fx("3", "2015-10-01T15:00:00", "Chelsea", "Arsenal", 1, 3),
    fx("4", "2016-05-02T20:00:00", "Chelsea", "Spurs", 2, 2),  # the match on screen
]
APPS = [
    ap("1", "2015-08-08T15:00:00", "Costa", "Chelsea", 2),
    ap("3", "2015-10-01T15:00:00", "Costa", "Chelsea", 0),
    ap("4", "2016-05-02T20:00:00", "Costa", "Chelsea", 5),
    ap("1", "2015-08-08T15:00:00", "Kane", "Spurs", 1),
]
NOW = "2016-05-02T20:00:00"


@pytest.fixture
def store(tmp_path, monkeypatch):
    build_graph.write({"football": (FIXTURES, APPS)}, tmp_path / "db")
    monkeypatch.setattr(graph, "_kv", None)
    graph._open_store(tmp_path / "db")
    assert graph._kv is not None
    yield
    monkeypatch.setattr(graph, "_kv", None)


def test_team_form_newest_first_from_the_teams_side(store):
    got = graph.team_form("football", "Chelsea", NOW, n=2)
    assert got == [
        {"date": "2015-10-01", "opponent": "Arsenal", "home": True, "score": "1-3", "result": "L"},
        {"date": "2015-09-01", "opponent": "Spurs", "home": False, "score": "0-0", "result": "D"},
    ]


def test_head_to_head_is_seen_from_a(store):
    got = graph.head_to_head("football", "Spurs", "Chelsea", NOW)
    assert [(g["score"], g["result"], g["home"]) for g in got] == [
        ("0-0", "D", True),
        ("1-2", "L", False),
    ]


def test_player_season_and_squad_stop_at_kickoff(store):
    s = graph.player_season("football", "Costa", NOW)
    assert (s["team"], s["matches"], s["totals"]["goals"]) == ("Chelsea", 2, 2)  # not the 5 tonight
    assert graph.player_season("football", "Costa", "2015-08-08T15:00:00") is None
    assert graph.squad("football", "Chelsea", NOW) == [
        {"name": "Costa", "matches": 2, "headline": "2 goals in 2"}
    ]


def test_a_later_match_never_appears(store):
    early = "2015-09-02T00:00:00"
    assert [g["date"] for g in graph.team_form("football", "Chelsea", early)] == [
        "2015-09-01",
        "2015-08-08",
    ]
    assert graph.player_season("football", "Costa", early)["matches"] == 1
    assert graph.head_to_head("football", "Chelsea", "Arsenal", early) == []
    assert (
        graph.team_form("football", "Chelsea", "2015-08-08") == []
    )  # a date alone excludes the day


def test_teams_lists_competition_season_and_matches(store):
    got = {t["team"]: t for t in graph.teams("football")}
    assert got["Chelsea"] == {
        "team": "Chelsea", "competition": "PL", "season": "2015/2016", "matches": 4}  # fmt: skip
    assert set(got) == {"Chelsea", "Spurs", "Arsenal"}


def test_engine_failure_returns_nothing_and_logs(store, monkeypatch, caplog):
    class Broken:
        def query(self, *a):
            raise RuntimeError("boom")

    monkeypatch.setattr(graph, "_kv", Broken())
    with caplog.at_level(logging.WARNING, "touchline.graph"):
        assert graph.team_form("football", "Chelsea", NOW) == []
        assert graph.head_to_head("football", "Chelsea", "Spurs", NOW) == []
        assert graph.player_season("football", "Costa", NOW) is None
        assert graph.squad("football", "Chelsea", NOW) == []
        assert graph.teams("football") == []
    assert "RuntimeError" in caplog.text


def test_no_store_is_the_same_fallback(monkeypatch):
    monkeypatch.setattr(graph, "_kv", None)
    assert graph.team_form("football", "Chelsea", NOW) == []
    assert graph.player_season("football", "Costa", NOW) is None
