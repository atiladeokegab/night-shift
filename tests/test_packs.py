"""The committed pre-match packs against the committed samples: no network."""

import json
from collections import Counter
from pathlib import Path

import pytest

from agent import packs
from core import predict

DATA = Path(__file__).resolve().parent.parent / "data"
ALL = [f"{sport}-{match_id}" for sport, match_id in packs.MATCHES]
MATCHES = [f"{sport}-{match_id}" for sport, match_id in packs.MATCHES if sport in predict.SHOTS]
CRICKET = "cricket-1298150"


def load(name):
    pack = json.loads((DATA / "packs" / f"{name}.json").read_text())
    sample = json.loads((DATA / "sample" / f"{name}.json").read_text())
    return pack, sample


@pytest.mark.parametrize("name", MATCHES)
def test_every_sample_shooter_is_a_pack_player(name):
    pack, sample = load(name)
    shooters = {m["players"]["shooter"] for m in sample["moments"] if "shooter" in m["players"]}
    assert shooters and shooters <= set(pack["players"])
    assert set(pack["teams"]) == {sample["header"]["home"], sample["header"]["away"]}


@pytest.mark.parametrize("name", MATCHES)
def test_nothing_pre_match_is_dated_on_or_after_the_match(name):
    pack, sample = load(name)
    day = sample["header"]["date"]
    assert pack["window"]["from"] <= pack["window"]["to"] < day
    dates = [s["date"] for p in pack["players"].values() for s in p["shots"]]
    assert dates and max(dates) < day
    assert all(len(p["shots"]) <= packs.SHOT_CAP for p in pack["players"].values())


@pytest.mark.parametrize("name", MATCHES)
def test_tonight_links_each_shot_to_the_moment_that_reveals_it(name):
    pack, sample = load(name)
    moments = sample["moments"]
    assert all(0 <= t["idx"] < len(moments) for t in pack["tonight"])
    # top 3 scorers: each made shot in the sample is a made tonight shot on the same moment
    made = [
        (m["players"]["shooter"], m["idx"])
        for m in moments
        if m["type"] == "Field goal" or (m["type"] == "Shot" and m["outcome"] == "Goal")
    ]
    top = Counter(player for player, _ in made).most_common(3)
    assert len(top) == 3
    for player, _ in top:
        sampled = Counter(idx for p, idx in made if p == player)
        linked = Counter(t["idx"] for t in pack["tonight"] if t["player"] == player and t["made"])
        assert sampled <= linked, player


def test_tonight_made_counts():
    made = {}
    for name in MATCHES:
        pack, _ = load(name)
        made[name] = Counter(t["player"] for t in pack["tonight"] if t["made"])
    assert made["basketball-0020500591"]["Kobe Bryant"] == 28  # 28 of 46 in the 81-point game
    assert made["basketball-0049700088"]["Michael Jordan"] == 15  # 15 of 35, 1998 Finals Game 6
    # football: tonight is every sample shot, shootout included
    pack, sample = load("football-3869685")
    shots = [m for m in sample["moments"] if m["type"] == "Shot"]
    assert len(pack["tonight"]) == len(shots)
    goals = Counter(m["players"]["shooter"] for m in shots if m["outcome"] == "Goal")
    assert made["football-3869685"] == goals and goals["Kylian Mbappé"] == 4


def test_football_zones():
    assert packs.football_zone(115, 40) == "six-yard box"
    assert packs.football_zone(108, 40) == "central box"  # the penalty spot
    assert packs.football_zone(108, 20) == "wide box"
    assert packs.football_zone(100, 40) == "outside box"


def test_cricket_players_and_window():
    pack, sample = load(CRICKET)
    names = {name for m in sample["moments"] for name in m["players"].values()}
    assert names <= set(pack["players"])
    day = sample["header"]["date"]
    assert pack["matches"] and max(m["date"] for m in pack["matches"]) < day
    assert pack["window"]["to"] < day
    assert all(set(m["teams"]) & set(pack["teams"]) for m in pack["matches"])
    kohli = pack["players"]["V Kohli"]
    assert kohli["games"] > 0 and kohli["batting"]["death"]["sr"] > 100
    assert pack["players"]["Arshdeep Singh"]["bowling"]["economy"] > 0


def test_cricket_tonight_reveals_each_ball_no_earlier_than_its_moment():
    pack, sample = load(CRICKET)
    moments, balls = sample["moments"], pack["tonight"]
    idx = [b["idx"] for b in balls]
    assert idx == sorted(idx) and idx[-1] == len(moments) - 1
    # every wicket moment is the ball it reveals; the innings totals match the sample's score
    for m in moments:
        if m["type"] == "Wicket":
            assert any(b["idx"] == m["idx"] and b["out"] == m["players"]["out"] for b in balls)
    for inn in (1, 2):
        final = max(m["score"]["runs"] for m in moments if m["period"] == inn)
        upto = max(m["idx"] for m in moments if m["period"] == inn)
        assert sum(b["runs"] for b in balls if b["innings"] == inn and b["idx"] <= upto) == final


@pytest.mark.parametrize("name", ALL)
def test_every_pack_record_is_dated_before_the_match_day(name):
    pack, sample = load(name)
    day = sample["header"]["date"]
    assert pack["window"]["from"] <= pack["window"]["to"] < day
    records = pack.get("matches", []) + [
        r for p in pack["players"].values() for r in p.get("shots", []) + p.get("results", [])
    ]
    assert records and all(r["date"] < day for r in records)


@pytest.mark.parametrize("name", ALL)
def test_everyone_named_in_the_moments_resolves_in_the_pack(name):
    pack, sample = load(name)
    named = {n for m in sample["moments"] for n in m["players"].values()}
    named |= {t["driver"] for m in sample["moments"] for t in m["score"].get("top", [])}
    assert named
    for n in named:
        assert predict.find(pack, n) == n


def test_f1_season_before_sao_paulo():
    pack, sample = load("f1-9636")
    assert pack["tonight"] == [] and len(pack["players"]) == 20
    max_ = pack["players"]["Max Verstappen"]
    assert max_["team"] == "Red Bull Racing" and max_["games"] == 20 and max_["wins"] == 7
    assert max_["results"][-1] == {
        "date": "2024-10-27",
        "race": "Mexico City",
        "grid": 2,
        "finish": 6,
    }
    # Bearman raced as 38 for Ferrari in Jeddah and as 50 for Haas in Baku: both count
    assert [r["race"] for r in pack["players"]["Oliver Bearman"]["results"]] == ["Jeddah", "Baku"]
