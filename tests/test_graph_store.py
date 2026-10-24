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


def test_basketball_row_counts_points_rebounds_assists_and_the_last_score():
    def row(kind, home="", visitor="", score="", p1=("Kobe", "LAL"), p2=("", "")):
        r = {"EVENTMSGTYPE": kind, "HOMEDESCRIPTION": home, "VISITORDESCRIPTION": visitor,
             "SCORE": score}  # fmt: skip
        for n, (name, abbr) in ((1, p1), (2, p2), (3, ("", ""))):
            r |= {f"PLAYER{n}_NAME": name, f"PLAYER{n}_TEAM_ABBREVIATION": abbr,
                  f"PLAYER{n}_TEAM_CITY": "LA" if abbr == "LAL" else "To",
                  f"PLAYER{n}_TEAM_NICKNAME": "Lakers" if abbr == "LAL" else "Raptors"}  # fmt: skip
        return r

    g = {"names": {}, "totals": {}, "score": None}
    meta = ("2006-01-22", "LAL", "TOR")
    for r in (
        row("1", home="Kobe 3PT Jump Shot (3 PTS) (Odom 1 AST)", score="0 - 3", p2=("Odom", "LAL")),
        row("3", home="Kobe Free Throw 1 of 2 (4 PTS)", score="0 - 4"),
        row("3", home="MISS Kobe Free Throw 2 of 2"),
        row("4", visitor="Bosh REBOUND", p1=("Bosh", "TOR")),
    ):
        build_graph._basketball_row(g, r, meta)
    assert g["score"] == (0, 4) and g["names"] == {"LAL": "LA Lakers", "TOR": "To Raptors"}
    assert g["totals"][("Kobe", "LAL")] == {"points": 4, "rebounds": 0, "assists": 0}
    assert g["totals"][("Odom", "LAL")]["assists"] == 1
    assert g["totals"][("Bosh", "TOR")]["rebounds"] == 1


def test_cricket_match_scores_innings_and_credits_runs_balls_wickets():
    def ball(batter, bowler, runs, wides=0, kind=None):
        d = {"batter": batter, "bowler": bowler, "runs": {"batter": runs, "total": runs + wides}}
        if wides:
            d["extras"] = {"wides": wides}
        if kind:
            d["wickets"] = [{"kind": kind, "player_out": batter}]
        return d

    m = {
        "info": {
            "dates": ["2022-10-23"],
            "teams": ["A", "B"],
            "players": {"A": ["Bat", "Bench"], "B": ["Bowl"]},
        },  # fmt: skip
        "innings": [
            {
                "team": "A",
                "overs": [
                    {
                        "deliveries": [
                            ball("Bat", "Bowl", 4),
                            ball("Bat", "Bowl", 0, wides=1),
                            ball("Bat", "Bowl", 0, kind="bowled"),
                        ]
                    }
                ],
            },  # fmt: skip
            {"team": "B", "overs": [{"deliveries": [ball("Bowl", "Bat", 1)]}]},
        ],
    }
    f, apps = build_graph.cricket_match(m)
    assert (f["home"], f["hg"], f["ag"], f["start"]) == ("A", 5, 1, "2022-10-23T23:59:59")
    got = {a["player"]: a["totals"] for a in apps}
    assert got == {"Bat": {"runs": 4, "balls": 2, "wickets": 0},
                   "Bowl": {"runs": 1, "balls": 1, "wickets": 1}}  # fmt: skip


def test_shipped_store_kobes_81_game_sees_only_earlier_games(monkeypatch):
    monkeypatch.setattr(graph, "_kv", None)
    graph._open_store()
    assert graph._kv is not None
    kickoff = "2006-01-22"  # the 81-point game against Toronto
    form = graph.team_form("basketball", "Los Angeles Lakers", kickoff, n=100)
    assert form and all(g["date"] < kickoff for g in form)
    assert all(g["opponent"] != "Toronto Raptors" or g["date"] < kickoff for g in form)
    kobe = graph.player_season("basketball", "Kobe Bryant", kickoff)
    assert kobe["season"] == "2005-06" and kobe["matches"] > 30
    after = graph.player_season("basketball", "Kobe Bryant", "2006-01-23")
    assert (
        after["totals"]["points"] - kobe["totals"]["points"] == 81
    )  # can go red: it is in the store
    assert graph.teams("cricket") and graph.teams("football") and graph.teams("basketball")


def test_cutoff_is_compared_in_utc_not_as_text(tmp_path, monkeypatch):
    # Chelsea v Spurs (4) kicks off 20:00 UTC on 2016-05-02. A kickoff of 2016-05-03 00:30+02:00 is
    # 22:30 UTC on the 2nd: the 20:00 match is earlier, but a text compare of 00:30 on the 3rd would
    # also pass anything up to then. Put a later match at 23:00 UTC on the 2nd to catch it.
    late = [*FIXTURES, fx("5", "2016-05-02T23:00:00", "Chelsea", "Arsenal", 9, 0)]
    build_graph.write({"football": (late, APPS)}, tmp_path / "db")
    monkeypatch.setattr(graph, "_kv", None)
    graph._open_store(tmp_path / "db")
    got = graph.team_form("football", "Chelsea", "2016-05-03T00:30:00+02:00")
    assert [g["date"] for g in got][0] == "2016-05-02" and got[0]["score"] == "2-2"  # not the 9-0
    # the other way: 23:30-02:00 is 01:30 UTC on the 3rd, so the 23:00 match is before it
    got = graph.team_form("football", "Chelsea", "2016-05-02T23:30:00-02:00")
    assert got[0]["score"] == "9-0"
    assert graph.team_form("football", "Chelsea", "not a time") == []


def test_a_team_name_shared_by_men_and_women_keeps_to_one_side(tmp_path, monkeypatch):
    def cx(mid, start, gender, hg):
        f = fx(mid, start, "Pakistan", "India", hg, 0, season="2022") | {"sport": "cricket"}
        return f | {"gender": gender, "competition": "T20I"}

    def cp(mid, start, gender, player):
        a = ap(mid, start, player, "Pakistan", 0, season="2022")
        return a | {"sport": "cricket", "gender": gender, "competition": "T20I",
                    "totals": {"runs": 10}}  # fmt: skip

    days = [("1", "female"), ("2", "male"), ("3", "female"), ("4", "male")]
    fixtures = [cx(m, f"2022-10-0{m}T23:59:59", g, int(m)) for m, g in days]
    apps = [
        cp(m, f"2022-10-0{m}T23:59:59", g, "Nida" if g == "female" else "Babar") for m, g in days
    ]
    build_graph.write({"cricket": (fixtures, apps)}, tmp_path / "db")
    monkeypatch.setattr(graph, "_kv", None)
    graph._open_store(tmp_path / "db")
    # before the 15th Pakistan's latest game was a men's one; before the 4th, a women's
    assert [g["score"] for g in graph.team_form("cricket", "Pakistan", "2022-10-15")] == [
        "4-0",
        "2-0",
    ]
    assert [g["score"] for g in graph.team_form("cricket", "Pakistan", "2022-10-04")] == [
        "3-0",
        "1-0",
    ]
    assert [s["name"] for s in graph.squad("cricket", "Pakistan", "2022-10-15")] == ["Babar"]
    assert [s["name"] for s in graph.squad("cricket", "Pakistan", "2022-10-04")] == ["Nida"]


def test_shipped_store_pakistan_squad_before_1298150_has_no_women(monkeypatch):
    monkeypatch.setattr(graph, "_kv", None)
    graph._open_store()
    names = {s["name"] for s in graph.squad("cricket", "Pakistan", "2022-10-23")}
    assert {"Babar Azam", "Mohammad Rizwan"} <= names
    assert not names & {"Muneeba Ali", "Nida Dar"}  # Pakistan's women's side
