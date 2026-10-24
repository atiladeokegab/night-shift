"""The committed pre-match packs against the committed samples: no network."""

import json
from collections import Counter
from pathlib import Path

import pytest

from agent import packs

DATA = Path(__file__).resolve().parent.parent / "data"
MATCHES = [f"{sport}-{match_id}" for sport, match_id in packs.MATCHES]


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
