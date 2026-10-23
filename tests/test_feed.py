"""The moment picker on hand-built feeds: no network."""

import json

from agent import feed

HEADER = {"sport": "football", "match_id": "1", "home": "Reds", "away": "Blues"}


def ev(kind, team="Reds", player="P", **extra):
    return {
        "id": extra.pop("id", kind),
        "type": {"name": kind},
        "team": {"name": team},
        "player": {"name": player},
        "period": 1,
        "minute": 10,
        "second": 5,
        **extra,
    }


def test_passes_and_carries_are_not_moments():
    events = [ev("Pass"), ev("Carry"), ev("Ball Receipt*"), ev("Pressure"), ev("Foul Committed")]
    assert feed.football_moments(HEADER, events) == []


def test_shots_goals_cards_and_own_goals_are_moments():
    events = [
        ev("Pass"),
        ev(
            "Shot", id="s1", player="Ann", shot={"outcome": {"name": "Saved"}, "statsbomb_xg": 0.31}
        ),
        ev(
            "Goal Keeper",
            team="Blues",
            player="Kim",
            related_events=["s1"],
            goalkeeper={"type": {"name": "Shot Saved"}},
        ),
        ev("Shot", player="Ann", shot={"outcome": {"name": "Goal"}}, location=[110.0, 40.0]),
        ev("Foul Committed", team="Blues", foul_committed={"card": {"name": "Yellow Card"}}),
        ev("Own Goal Against", team="Reds", player="Bo"),
    ]
    moments = feed.football_moments(HEADER, events)
    assert [(m["type"], m["outcome"]) for m in moments] == [
        ("Shot", "Saved"),
        ("Shot", "Goal"),
        ("Foul Committed", "Yellow Card"),
        ("Own Goal Against", "Own goal"),
    ]
    assert moments[0]["players"] == {"shooter": "Ann", "keeper": "Kim"}
    assert moments[1]["score"] == {"home": 1, "away": 0} and moments[1]["x"] == 110.0
    assert moments[3]["score"] == {"home": 1, "away": 1}  # an own goal counts for the other side
    assert [m["idx"] for m in moments] == [0, 1, 2, 3]


def test_players_go_by_their_lineup_nickname_else_their_full_name():
    messi = {"id": 5503, "name": "Lionel Andrés Messi Cuccittini"}
    events = [
        ev("Shot", player=None, shot={"outcome": {"name": "Goal"}}) | {"player": messi},
        ev("Shot", player="Hugo Lloris", shot={"outcome": {"name": "Saved"}}),
    ]
    moments = feed.football_moments(HEADER, events, {5503: "Lionel Messi"})
    assert [m["players"]["shooter"] for m in moments] == ["Lionel Messi", "Hugo Lloris"]


def test_name_overrides_beat_statsbomb_nicknames(monkeypatch):
    lineups = [{"lineup": [{"player_id": 22097, "player_nickname": "Randal Kolo"}]}]
    monkeypatch.setattr(feed, "_fetch", lambda *a, **k: json.dumps(lineups).encode())
    assert feed.statsbomb_nicknames("3869685")[22097] == "Kolo Muani"


def ball(batter=0, extras=None, wicket=None, ball="0.1"):
    d = {
        "batter": "Bat",
        "bowler": "Bowl",
        "non_striker": "Ns",
        "actual_delivery": ball,
        "runs": {
            "batter": batter,
            "extras": sum((extras or {}).values()),
            "total": batter + sum((extras or {}).values()),
        },
    }
    if extras:
        d["extras"] = extras
    if wicket:
        d["wickets"] = [{"player_out": "Bat", "kind": wicket, "fielders": [{"name": "Fld"}]}]
    return d


def match(*innings):
    return {
        "info": {"overs": 20, "teams": ["A", "B"]},
        "innings": [
            {"team": t, "overs": [{"over": 0, "deliveries": list(ds)}], **x} for t, ds, x in innings
        ],
    }


def test_dot_balls_and_singles_are_not_moments_until_the_last_ball():
    m = match(("A", [ball(0), ball(1), ball(0), ball(2)], {}))
    moments = feed.cricket_moments({"match_id": "9"}, m)
    assert [mo["type"] for mo in moments] == ["Last ball"]


def test_fours_sixes_wickets_and_no_balls_are_moments():
    deliveries = [
        ball(0),
        ball(4),
        ball(6),
        ball(0, wicket="bowled"),
        ball(1, {"noballs": 1}),
        ball(0, {"wides": 1}),
        ball(1),
        ball(0),
    ]
    moments = feed.cricket_moments({"match_id": "9"}, match(("A", deliveries, {})))
    assert [mo["type"] for mo in moments] == ["Four", "Six", "Wicket", "No ball", "Last ball"]
    assert moments[2]["players"]["fielder"] == "Fld" and moments[2]["score"]["wickets"] == 1
    assert moments[3]["detail"]["free_hit"] is False  # the no-ball itself
    assert moments[-1]["score"] == {"runs": 4 + 6 + 2 + 1 + 1, "wickets": 1}


def test_free_hit_runs_to_the_next_legal_ball():
    deliveries = [ball(0, {"noballs": 1}), ball(0, {"wides": 1}), ball(4), ball(4), ball(0)]
    moments = feed.cricket_moments({"match_id": "9"}, match(("A", deliveries, {})))
    assert [mo["detail"]["free_hit"] for mo in moments if mo["type"] == "Four"] == [True, False]


def test_close_chase_in_the_last_two_overs_calls_every_ball():
    m = match(
        (
            "B",
            [ball(1, ball="18.1"), ball(0, ball="18.2"), ball(1, ball="18.3")],
            {"target": {"runs": 20}},
        )
    )
    m["innings"][0]["overs"][0]["over"] = 18
    moments = feed.cricket_moments({"match_id": "9"}, m)
    assert [mo["type"] for mo in moments] == ["Chase", "Chase", "Last ball"]
    assert moments[0]["score"]["target"] == 20


def test_held_out_and_demo_matches():
    assert feed.held_out("football", "105") and not feed.held_out("football", "106")
    assert ("cricket", "1298150") in feed.DEMO and ("football", "3906390") in feed.DEMO
    assert {("basketball", "0049700088"), ("basketball", "0020500591")} <= feed.DEMO


def test_cricket_clock_counts_legal_balls_within_each_over():
    """Real Cricsheet has no actual_delivery: the clock comes from the over and its legal balls."""

    def four(**kw):
        d = ball(batter=4, **kw)
        del d["actual_delivery"]
        return d

    overs = [
        {"over": 0, "deliveries": [four() for _ in range(6)]},
        # a wide and a no-ball are re-bowled, so they share the next legal ball's number
        {
            "over": 1,
            "deliveries": [four(extras={"wides": 1}), four(), four(extras={"noballs": 1})]
            + [four() for _ in range(5)],
        },
        {"over": 2, "deliveries": [four() for _ in range(6)]},
    ]
    m = {"info": {"overs": 20}, "innings": [{"team": "A", "overs": overs}]}
    clocks = [x["clock"] for x in feed.cricket_moments({"match_id": "9"}, m)]
    assert clocks == (
        [f"0.{b}" for b in range(1, 7)]
        + ["1.1", "1.1", "1.2", "1.2", "1.3", "1.4", "1.5", "1.6"]
        + [f"2.{b}" for b in range(1, 7)]
    )


BALL = {
    "sport": "basketball",
    "match_id": "0049700088",
    "home": "Utah Jazz",
    "away": "Chicago Bulls",
}


def play(n, kind, clock, desc, side="away", p1="Michael Jordan", p2="", period=4, other=""):
    home, away = ("Utah", "Jazz"), ("Chicago", "Bulls")
    t1, t2 = (away, home) if side == "away" else (home, away)
    return {
        "EVENTNUM": str(n),
        "EVENTMSGTYPE": str(kind),
        "PERIOD": str(period),
        "PCTIMESTRING": clock,
        "HOMEDESCRIPTION": desc if side == "home" else other,
        "VISITORDESCRIPTION": desc if side == "away" else other,
        "PLAYER1_NAME": p1,
        "PLAYER1_TEAM_CITY": t1[0],
        "PLAYER1_TEAM_NICKNAME": t1[1],
        "PLAYER2_NAME": p2,
        "PLAYER2_TEAM_CITY": t2[0] if p2 else "",
        "PLAYER2_TEAM_NICKNAME": t2[1] if p2 else "",
    }


def test_basketball_picks_lead_changes_steals_and_the_buzzer():
    rows = [
        # an opening basket is no moment: no tie, no lead change, not the closing minutes
        play(1, 1, "11:30", "Malone Jump Shot (2 PTS)", side="home", p1="Karl Malone"),
        play(2, 2, "11:10", "MISS Jordan Jump Shot"),
        play(3, 3, "10:50", "Jordan Free Throw 1 of 2 (1 PTS)"),
        play(4, 1, "10:40", "Pippen 3PT Jump Shot (3 PTS)", p1="Scottie Pippen"),
        # the turnover is on Utah's side, the steal on Chicago's: a steal, credited to Jordan
        play(
            5,
            5,
            "0:18",
            "Malone Turnover",
            side="home",
            p1="Karl Malone",
            p2="Michael Jordan",
            other="Jordan STEAL (1 STL)",
        ),
        play(6, 1, "0:05", "Jordan 17' Jump Shot (3 PTS)"),
        play(7, 13, "0:00", ""),
    ]
    rows[4]["PLAYER2_TEAM_CITY"], rows[4]["PLAYER2_TEAM_NICKNAME"] = "Chicago", "Bulls"
    ms = feed.basketball_moments(BALL, rows)
    assert [m["type"] for m in ms] == ["Field goal", "Steal", "Field goal", "End of game"]
    assert ms[0]["detail"]["lead_change"] and ms[0]["score"] == {"home": 2, "away": 4}
    assert ms[1]["players"] == {"stealer": "Michael Jordan", "lost_by": "Karl Malone"}
    assert ms[1]["team"] == "Chicago Bulls" and ms[1]["detail"]["play"] == "Jordan STEAL (1 STL)"
    assert ms[2]["players"] == {"shooter": "Michael Jordan"} and ms[2]["clock"] == "00:05"
    assert ms[2]["detail"]["player_points"] == 3 and ms[-1]["score"] == {"home": 2, "away": 6}


def test_basketball_keeps_every_basket_of_a_big_night_and_the_record_free_throw():
    rows, pts = [], 0
    for n in range(41):  # 41 two-pointers in the 1st quarter: 82 points
        pts += 2
        rows.append(
            play(n, 1, "11:00", f"Bryant Jump Shot ({pts} PTS)", p1="Kobe Bryant", period=1)
        )
    rows.append(play(99, 3, "0:43", "Bryant Free Throw 1 of 2 (83 PTS)", p1="Kobe Bryant"))
    ms = feed.basketball_moments(BALL, rows)
    points = [m["detail"]["player_points"] for m in ms]
    assert points[0] == 30 and points[-1] == 83  # the 30 milestone first, the record FT last
    assert all(p in points for p in range(40, 83, 2))


def test_nba_rows_rejects_an_id_that_is_not_a_game():
    import pytest

    for bad in ("49700088", "00497000ab", "0019700088", "../etc/passwd"):
        with pytest.raises(KeyError):
            feed.nba_rows(bad)
