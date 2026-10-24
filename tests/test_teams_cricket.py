"""/teams on the real graph for the cricket demo match (#373): Cricsheet files men's and women's
T20Is under one team name, so a squad must never list the other side's players."""

import pytest
from fastapi.testclient import TestClient

from core import teams
from core.app import Deps, create_app
from core.store import Store
from data.matches import list_matches, load_moments

WOMEN = {"Muneeba Ali", "Nida Dar", "S Mandhana"}  # Pakistan's and India's women's sides


@pytest.fixture
def client(tmp_path):
    teams._cache.clear()
    deps = Deps(list_matches, load_moments, lambda m, h: {})
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as c:
        yield c


def test_pakistan_v_india_squads_hold_no_women(client):
    body = client.get("/teams/cricket/1298150").json()  # the real graph, not a recording
    squads = {t["team"]: {p["name"] for p in t["squad"]} for t in body["teams"]}
    assert squads["Pakistan"] and squads["India"], (
        "the graph is off: the test would pass on nothing"
    )
    assert {"Babar Azam"} <= squads["Pakistan"] and {"V Kohli"} <= squads["India"]
    assert not (squads["Pakistan"] | squads["India"]) & WOMEN
    assert all(g["date"] < "2022-10-23" for t in body["teams"] for g in t["form"])
    # India's women's side played the week before: their opponents must not show up in its form
    india = next(t for t in body["teams"] if t["team"] == "India")
    assert all(
        g["opponent"] not in {"Thailand", "Bangladesh"} or g["date"] < "2022-10-01"
        for g in india["form"]
    )
