"""The moment picker on hand-built feeds: no network."""

import json
from datetime import timedelta
from pathlib import Path

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
    assert ("cricket", "1298150") in feed.DEMO and ("football", "3754092") in feed.DEMO
    assert {("basketball", "0049700088"), ("basketball", "0020500591")} <= feed.DEMO
    assert ("f1", "9636") in feed.DEMO


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


# --- f1 ---

RACE = {"sport": "f1", "match_id": "9", "laps": 3}


def at(seconds: float) -> str:
    seconds += 60  # the grid is read a few seconds before the start
    return f"2024-07-07T14:{int(seconds) // 60:02d}:{seconds % 60:06.3f}+00:00"


def race_rows():
    """Four cars, three laps: a pass sent in reverse order, one handed straight back, one where
    the passed car drops first, a pit stop for softs that swaps places below P1, and Gasly's laps
    stopping after lap 1 with nothing to say he is out."""
    drivers = [
        {"driver_number": n, "first_name": f, "last_name": last, "team_name": t}
        for n, f, last, t in [
            (44, "Lewis", "Hamilton", "Mercedes"),
            (1, "Max", "Verstappen", "Red Bull Racing"),
            (4, "Lando", "Norris", "McLaren"),
            (10, "Pierre", "Gasly", "Alpine"),
        ]
    ]
    pos = lambda t, n, p: {"date": at(t), "driver_number": n, "position": p}  # noqa: E731
    return {
        "drivers": drivers,
        "race_control": [
            {"date": at(0), "category": "Other", "message": "SESSION STARTED"},
            {"date": at(100), "category": "SafetyCar", "message": "SAFETY CAR DEPLOYED"},
            {"date": at(110), "category": "Other", "message": "LOW GRIP CONDITIONS"},
            {"date": at(170), "category": "Flag", "flag": "CHEQUERED", "message": "CHEQUERED FLAG"},
        ],
        "position": [
            pos(-5, 1, 1),
            pos(-5, 44, 2),
            pos(-5, 4, 3),
            pos(-5, 10, 4),
            pos(20, 1, 2),
            pos(20, 44, 1),  # one timestamp, the passed car's row first
            pos(25, 4, 1),
            pos(25, 44, 3),
            pos(28, 4, 3),
            pos(28, 44, 1),  # handed back in 3 s
            pos(60, 1, 3),
            pos(64, 4, 2),  # Verstappen drops, Norris moves up 4 s later
            pos(114, 4, 3),
            pos(114, 1, 2),  # Norris pits (the feed lags 6 s): Verstappen's P2 is not an overtake
        ],
        "intervals": [
            {"date": at(150), "driver_number": 44, "gap_to_leader": 0.0},
            {"date": at(150), "driver_number": 1, "gap_to_leader": 2.1},
            {"date": at(150), "driver_number": 4, "gap_to_leader": 1.0},  # stale: behind P2
            {"date": at(180), "driver_number": 1, "gap_to_leader": 1.2},  # over the line
        ],
        "pit": [{"date": at(108), "driver_number": 4, "lap_number": 2, "pit_duration": 21.0}],
        "stints": [
            {"driver_number": n, "lap_start": 1, "compound": "MEDIUM"} for n in (1, 4, 10, 44)
        ]
        + [{"driver_number": 4, "lap_start": 3, "compound": "SOFT"}],
        "laps": [
            {
                "date_start": at(60 * (k - 1) + 1),
                "driver_number": n,
                "lap_number": k,
                "lap_duration": 60.0,
            }
            for k in (1, 2, 3)
            for n in (1, 4, 44)
        ]
        + [{"date_start": at(1), "driver_number": 10, "lap_number": 1, "lap_duration": None}],
    }


def test_f1_calls_passes_pit_stops_the_safety_car_and_the_flag():
    ms = feed.f1_moments(RACE, race_rows())
    calls = [(m["clock"], m["type"], m["players"].get("driver"), m["outcome"]) for m in ms]
    assert calls == [
        ("00:00", "Lights out", None, "race start"),
        ("00:40", "Lead change", "Lewis Hamilton", "P1 on track"),  # once it has held 20 s
        ("01:24", "Overtake", "Lando Norris", "P2 on track"),
        ("01:40", "Safety car", None, "Safety car deployed"),
        ("01:50", "Conditions", None, "Low grip conditions"),
        ("02:01", "Last lap", None, "final lap"),
        ("02:09", "Pit stop", "Lando Norris", "pits for soft tyres"),  # at pit exit
        ("03:10", "Finish", None, "chequered flag"),
    ]  # no flap at 00:25, no overtake from the stop, and no retirement guessed for Gasly
    assert ms[1]["players"] == {"driver": "Lewis Hamilton", "passed": "Max Verstappen"}
    assert ms[2]["players"]["passed"] == "Max Verstappen" and ms[2]["period"] == 2
    assert ms[6]["team"] == "McLaren" and ms[6]["detail"] == {
        "tyres": "soft",
        "pit_lane_time": "21.0 seconds in the pit lane",  # never read as the stop itself
    }
    assert ms[-1]["players"] == {"winner": "Lewis Hamilton"}


def red_flag_rows():
    """race_rows with a red flag at 00:30: as at Monaco and Suzuka 2024, each car's tyre change
    while parked in the lane comes as a pit row with the whole stoppage as its lane time."""
    rows = race_rows()
    rows["race_control"].insert(
        1, {"date": at(30), "category": "Flag", "flag": "RED", "message": "RED FLAG"}
    )
    rows["pit"] += [
        {"date": at(31), "driver_number": 44, "lap_number": 1, "pit_duration": 2358.0},  # Monaco
        {"date": at(32), "driver_number": 1, "lap_number": 1, "pit_duration": 1577.6},  # Suzuka
        {"date": at(5), "driver_number": 10, "lap_number": 1, "pit_duration": 40.0},  # flag shown
    ]
    return rows


def test_f1_a_tyre_change_under_a_red_flag_is_not_a_pit_stop():
    stops = [m for m in feed.f1_moments(RACE, red_flag_rows()) if m["type"] == "Pit stop"]
    assert [(m["players"]["driver"], m["clock"]) for m in stops] == [("Lando Norris", "02:09")]


def test_f1_monaco_2024_red_flag_tyre_changes_are_not_pit_stops():
    # Real OpenF1 rows from session 9523: the top three, the lap-1 red flag, the restart, and
    # each car's tyre change in the parked pit lane (2358 s), once called as stops on lap 30.
    rows = json.loads(
        (Path(__file__).parent / "fixtures" / "openf1-9523-red-flag.json").read_text()
    )
    race = {"sport": "f1", "match_id": "9523", "laps": 78}
    ms = feed.f1_moments(race, rows)
    assert [m["type"] for m in ms] == ["Lights out", "Red flag"]


def test_f1_standing_puts_a_pitting_car_in_the_pit_lane_without_reading_ahead():
    ms = feed.f1_moments(RACE, race_rows())  # Norris pits at 01:48, his new place lands 6 s later
    during = next(m for m in ms if m["type"] == "Conditions")  # 01:50
    top = [(c["pos"], c["driver"], c["gap"]) for c in during["score"]["top"]]
    assert top[:2] == [(1, "Lewis Hamilton", "leader"), (3, "Max Verstappen", "")]  # A-1.4
    assert top[-1] == (None, "Lando Norris", "in the pit lane")
    before = next(m for m in ms if m["type"] == "Safety car")  # 01:40: no stop yet
    assert before["score"]["top"][1]["driver"] == "Lando Norris"


def test_f1_standing_leaves_out_a_gap_that_lags_the_car_ahead():
    top = feed.f1_moments(RACE, race_rows())[-1]["score"]["top"][:3]  # the flag: live gaps
    assert [(c["driver"], c["gap"]) for c in top] == [
        ("Lewis Hamilton", "leader"),
        ("Max Verstappen", "1.2 seconds"),  # "+1.2s" was misread
        ("Lando Norris", ""),
    ]


def known(rows: dict, t) -> dict:
    """The feed as it stood at t: rows dated after t are not sent yet, a lap's duration is
    never known in time, and a stop's lane time and new tyre arrive as the car leaves."""
    by = lambda key: [r for r in rows[key[0]] if feed._when(r[key[1]]) <= t]  # noqa: E731
    out = {"drivers": rows["drivers"]}
    for name in ("position", "intervals", "race_control"):
        out[name] = by((name, "date"))
    out["laps"] = [{**r, "lap_duration": None} for r in by(("laps", "date_start"))]
    out["pit"], done = [], set()
    for r in by(("pit", "date")):
        if feed._when(r["date"]) + timedelta(seconds=r["pit_duration"]) <= t:
            out["pit"].append(r)
            done.add((r["driver_number"], r["lap_number"] + 1))
        else:
            out["pit"].append({**r, "pit_duration": None})
    out["stints"] = [
        r
        for r in rows["stints"]
        if r["lap_start"] == 1 or (r["driver_number"], r["lap_start"]) in done
    ]
    return out


def test_f1_no_moment_reads_a_row_from_later_in_the_feed():
    slow = race_rows()  # Gasly is slow, not out: his lap 2 lands after the others start lap 3
    slow["laps"].append({"date_start": at(150), "driver_number": 10, "lap_number": 2})
    for rows in (race_rows(), slow, red_flag_rows()):
        start = feed._when(rows["race_control"][0]["date"])
        ms = feed.f1_moments(RACE, rows)
        secs = lambda m: 60 * int(m["clock"][:2]) + int(m["clock"][3:])  # noqa: E731
        for t in range(200):  # A-1.4: what is called by t comes from the feed as it stood at t
            then = feed.f1_moments(RACE, known(rows, start + timedelta(seconds=t)))
            assert [m for m in then if secs(m) <= t] == [m for m in ms if secs(m) <= t], t


def test_openf1_rejects_a_session_key_that_is_not_a_number():
    import pytest

    for bad in ("latest", "9558&x=1", "../etc"):
        with pytest.raises(KeyError):
            feed.openf1("laps", bad)


def test_womens_sides_go_by_the_country_name():
    meta = {
        "match_id": 3906390,
        "home_team": {"home_team_name": "Spain Women's"},
        "away_team": {"away_team_name": "England Women's"},
    }
    header = feed.football_header(meta)
    assert (header["home"], header["away"]) == ("Spain", "England")
    goal = ev("Shot", team="Spain Women's", shot={"outcome": {"name": "Goal"}})
    [m] = feed.football_moments(header, [goal])
    assert m["team"] == "Spain" and m["score"] == {"home": 1, "away": 0}


def test_football_full_time_is_called_at_the_whistle_that_ends_the_match():
    def whistle(period, minute):
        return [
            ev("Half End", team=t, id=f"end{period}{t}", period=period, minute=minute)
            for t in ("Reds", "Blues")
        ]

    def goal(team, period):
        return ev(
            "Shot",
            team=team,
            id=f"goal{period}{team}",
            period=period,
            shot={"outcome": {"name": "Goal"}},
        )

    def called(stage, events):
        return [
            (m["period"], m["clock"])
            for m in feed.football_moments({**HEADER, "stage": stage}, events)
            if m["type"] == "Full time"
        ]

    win = [goal("Reds", 2), *whistle(1, 46), *whistle(2, 94)]
    assert called("Final", win) == [(2, "94:05")]
    [ft] = [m for m in feed.football_moments(HEADER, win) if m["type"] == "Full time"]
    assert (ft["outcome"], ft["team"], ft["score"]) == ("Full time", "", {"home": 1, "away": 0})
    # a level knockout tie goes on: no whistle at 90 or 120 is full time, the shoot-out's is
    draw = [*whistle(2, 95), goal("Reds", 3), goal("Blues", 4), *whistle(4, 122), *whistle(5, 130)]
    assert called("Final", draw) == [(5, "130:05")]
    assert (
        called("Final", draw[:-2]) == []
    )  # A-1.4: the same match cut at 120 minutes calls nothing
    assert called("Group Stage", whistle(2, 93)) == [(2, "93:05")]  # a group draw ends at 90


def test_a_football_quiet_spell_of_3_minutes_carries_the_ball_never_its_end():
    def play(kind, team, minute, second, holder=None, **extra):
        return ev(
            kind,
            team=team,
            id=f"{kind}{minute}{second}",
            minute=minute,
            second=second,
            possession_team={"name": holder or team},
            location=[61.6, 7.7],
            **extra,
        )

    shot = {"shot": {"outcome": {"name": "Off T"}}}
    events = [
        play("Shot", "Reds", 10, 0, **shot),
        play("Pass", "Blues", 10, 10),  # too soon after the shot
        play("Dispossessed", "Blues", 10, 30),  # losing the ball, not having it
        play("Pass", "Reds", 10, 40, holder="Blues"),  # the side without the ball
        play("Carry", "Blues", 10, 45),
        play("Shot", "Blues", 13, 30, **shot),
        play("Pass", "Reds", 13, 55),  # a gap of 90 s: no quiet spell
        play("Shot", "Reds", 15, 0, **shot),
        play("Pass", "Blues", 18, 10),  # 20 s before the next moment: its build-up
        play("Shot", "Blues", 18, 30, **shot),
        play("Pass", "Reds", 46, 0, period=2),  # the next period's play
    ]
    first, short, built_up, last = feed.football_moments(HEADER, events)
    assert first["ball"] == {"clock": "10:45", "team": "Blues", "x": 61.6, "y": 7.7}
    assert not any("ball" in m for m in (short, built_up, last))
