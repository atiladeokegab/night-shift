"""Predictions (#119): profiles, next-to-score odds and shot points from the committed packs."""

import copy
import re

import pytest

from agent.commentator import run_tool
from core import predict
from data.matches import load_moments, match_header

SHOTS = [("basketball", "0020500591", "Kobe"), ("football", "3869685", "Messi")]
ALL = [*SHOTS, ("basketball", "0049700088", "Jordan"), ("cricket", "1298150", "Kohli")]


def load(sport, match_id):
    return predict.load_pack(sport, match_id), load_moments(match_id)


def with_future(pack, idx, player):
    """The pack plus a made shot (or a ball) one moment after idx, marked so it shows if used."""
    future = copy.deepcopy(pack)
    shot = copy.deepcopy(next(t for t in pack["tonight"] if t.get("player", t.get("batter"))))
    shot.update(idx=idx + 1, x=999, y=999, made=True, xg=0.99, runs=6, out="")
    shot["player" if "player" in shot else "batter"] = player
    future["tonight"].append(shot)
    return future


@pytest.mark.parametrize("sport,match_id,who", ALL)
def test_a_shot_after_the_moment_on_screen_changes_nothing(sport, match_id, who):
    pack, moments = load(sport, match_id)
    idx = len(moments) // 2
    name = predict.find(pack, who)
    future = with_future(pack, idx, name)
    assert predict.profile_text(future, moments, idx, who) == predict.profile_text(
        pack, moments, idx, who
    )
    # the same shot one moment earlier does count: the check above can go red
    now = with_future(pack, idx - 1, name)
    assert predict.profile_text(now, moments, idx, who) != predict.profile_text(
        pack, moments, idx, who
    )
    if sport != "cricket":
        assert predict.odds_text(future, moments, idx) == predict.odds_text(pack, moments, idx)
        points = predict.shot_points(future, moments, idx, who)
        assert points == predict.shot_points(pack, moments, idx, who)
        assert all(t["idx"] <= idx for t in points["tonight"])
        assert 999.0 in [t["x"] for t in predict.shot_points(now, moments, idx, who)["tonight"]]


@pytest.mark.parametrize("sport,match_id,who", ALL)
def test_the_tools_see_only_the_match_so_far(sport, match_id, who):
    """run_tool on the moments up to k answers as if the pack ended at k."""
    pack, moments = load(sport, match_id)
    header = match_header(match_id)
    for k in (0, len(moments) // 3, len(moments) - 2):
        cut = {**pack, "tonight": [t for t in pack["tonight"] if t["idx"] <= k]}
        past = moments[: k + 1]
        said = run_tool("get_player_profile", {"name": who}, header, past)
        assert said == predict.profile_text(cut, moments, k, who)
        odds = run_tool("get_next_score_odds", {}, header, past)
        assert odds == predict.odds_text(cut, moments, k)


@pytest.mark.parametrize("sport,match_id,who", SHOTS + [("basketball", "0049700088", "")])
def test_odds_sum_to_one_per_team(sport, match_id, who):
    pack, moments = load(sport, match_id)
    for idx in (0, len(moments) // 2, len(moments) - 1):
        odds = predict.next_score_odds(pack, moments, idx)
        assert set(odds) == set(pack["teams"])
        for rows in odds.values():
            assert sum(r["p"] for r in rows) == pytest.approx(1.0)
            assert all(0 <= r["p"] <= 1 for r in rows)
            assert [r["p"] for r in rows] == sorted((r["p"] for r in rows), reverse=True)


def test_a_small_sample_says_so():
    pack, moments = load("football", "3869685")
    thuram = pack["players"]["Marcus Thuram"]
    assert thuram["attempts"] < predict.SMALL
    assert "small sample" in predict.profile_text(pack, moments, 0, "Marcus Thuram")
    messi = predict.profile_text(pack, moments, 0, "Messi").splitlines()[0]
    assert pack["players"]["Lionel Messi"]["attempts"] >= predict.SMALL
    assert "small sample" not in messi
    flagged = re.findall(
        r"(\w[^;:(]*?) \d+% \([^)]*small sample\)", predict.odds_text(pack, moments, 0)
    )
    assert flagged and all(pack["players"][n.strip()]["attempts"] < predict.SMALL for n in flagged)
    cricket, balls = load("cricket", "1298150")
    kohli = predict.profile_text(cricket, balls, 0, "Kohli")
    assert "Bowling: 0 wickets in 6 balls" in kohli and "small sample" in kohli


def test_answers_cite_the_counts():
    pack, moments = load("basketball", "0020500591")
    kobe = pack["players"]["Kobe Bryant"]
    idx = len(moments) - 1
    mine = [t for t in pack["tonight"] if t["player"] == "Kobe Bryant"]
    said = predict.profile_text(pack, moments, idx, "kobe")
    assert f"made {kobe['made']} of {kobe['attempts']}" in said
    assert f"Tonight so far: {sum(t['made'] for t in mine)} of {len(mine)} attempts" in said
    mid = kobe["zones"]["Mid-Range"]
    assert f"Mid-Range: {round(100 * mid['made'] / mid['att'])}% before tonight" in said
    assert f"({mid['made']} of {mid['att']})" in said
    assert "Kobe Bryant " in predict.odds_text(pack, moments, idx)


def test_shot_points_shape():
    pack, moments = load("basketball", "0020500591")
    idx = 10
    out = predict.shot_points(pack, moments, idx, "kobe bryant")
    assert set(out) == {"player", "sport", "season", "tonight", "zones"}
    assert (out["player"], out["sport"]) == ("Kobe Bryant", "basketball")
    assert out["season"] and out["tonight"] and out["zones"]
    assert all(
        set(s) == {"x", "y", "made", "zone"} and isinstance(s["x"], float) for s in out["season"]
    )
    assert all(set(t) == {"x", "y", "made", "idx"} and t["idx"] <= idx for t in out["tonight"])
    assert all(set(z) == {"zone", "attempts", "made", "rate"} for z in out["zones"])
    zones = pack["players"]["Kobe Bryant"]["zones"]
    assert sum(z["attempts"] for z in out["zones"]) == sum(z["att"] for z in zones.values())
    foot, fm = load("football", "3869685")
    assert predict.shot_points(foot, fm, 5, "Mbappe")["player"] == "Kylian Mbappé"


def test_shot_points_refuses_cricket_a_bad_moment_and_a_stranger():
    cricket, balls = load("cricket", "1298150")
    with pytest.raises(ValueError):
        predict.shot_points(cricket, balls, 0, "Kohli")
    pack, moments = load("basketball", "0020500591")
    for idx in (-1, len(moments)):  # -1 would otherwise read the last moment: the whole match
        with pytest.raises(ValueError):
            predict.shot_points(pack, moments, idx, "Kobe")
    with pytest.raises(KeyError):
        predict.shot_points(pack, moments, 0, "Nobody Atall")


def test_names_resolve_loosely():
    cricket, _ = load("cricket", "1298150")
    assert predict.find(cricket, "Virat Kohli") == "V Kohli"
    foot, _ = load("football", "3869685")
    assert predict.find(foot, "messi") == "Lionel Messi"
    assert predict.find(foot, "Angel Di Maria") == "Ángel Di María"


def test_no_pack_no_numbers():
    assert predict.load_pack("f1", "9558") is None
    assert predict.load_pack("football", "../../etc") is None
    header = match_header("9558")
    past = load_moments("9558")[:3]
    for tool in ("get_player_profile", "get_next_score_odds"):
        assert run_tool(tool, {"name": "x"}, header, past) == "No pre-match record for this event."
    cricket, balls = load("cricket", "1298150")
    assert "basketball and football" in predict.odds_text(cricket, balls, 3)
