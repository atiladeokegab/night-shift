"""The moment picker on hand-built feeds: no network."""

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
