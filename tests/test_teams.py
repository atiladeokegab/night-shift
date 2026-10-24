"""GET /teams/{sport}/{match_id} (#375): both sides' form, head-to-head and squad from the graph,
cut at the match's start, empty when the graph has nothing, cached for a minute."""

import pytest
from fastapi.testclient import TestClient

from core import graph, teams
from core.app import Deps, create_app
from core.store import Store
from data.matches import list_matches, load_moments

GAME = {"date": "2016-04-20", "opponent": "Everton", "home": True, "score": "2-1", "result": "W"}
PLAYER = {"name": "Eden Hazard", "matches": 21, "headline": "9 goals in 21"}


@pytest.fixture
def client(tmp_path):
    teams._cache.clear()
    deps = Deps(list_matches, load_moments, lambda m, h: {})
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as c:
        yield c


def stub(monkeypatch, calls):
    def fake(name, rows):
        def f(*args, **kw):
            calls.append((name, args))
            return rows

        monkeypatch.setattr(graph, name, f, raising=False)

    fake("team_form", [GAME])
    fake("head_to_head", [GAME])
    fake("squad", [PLAYER] * 12)


def test_route_shape_and_cut_at_the_start(client, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    body = client.get("/teams/football/3754092").json()
    assert [t["team"] for t in body["teams"]] == ["Chelsea", "Tottenham Hotspur"]
    assert body["teams"][0]["form"] == [GAME] and len(body["teams"][0]["squad"]) == teams.SQUAD_MAX
    assert body["head_to_head"] == [GAME]
    assert calls and all(a[-1] == "2016-05-02" for _, a in calls)  # the match's own date, always


def test_empty_graph_is_empty_sections_not_an_error(client, monkeypatch):
    for name in ("team_form", "head_to_head", "squad"):
        monkeypatch.setattr(graph, name, lambda *a, **k: None, raising=False)
    r = client.get("/teams/football/3754092")
    assert r.status_code == 200
    assert r.json()["head_to_head"] == [] and r.json()["teams"][0]["form"] == []


def test_a_failing_graph_is_empty_not_a_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("engine")

    for name in ("team_form", "head_to_head", "squad"):
        monkeypatch.setattr(graph, name, boom, raising=False)
    assert client.get("/teams/football/3754092").status_code == 200


def test_second_request_is_cached(client, monkeypatch):
    calls = []
    stub(monkeypatch, calls)
    client.get("/teams/football/3754092")
    n = len(calls)
    client.get("/teams/football/3754092")
    assert len(calls) == n


def test_unknown_match_or_wrong_sport_is_404(client):
    assert client.get("/teams/football/nope").status_code == 404
    assert client.get("/teams/cricket/3754092").status_code == 404


def test_squad_falls_back_to_the_pack_when_the_graph_has_none(client, monkeypatch):
    monkeypatch.setattr(graph, "squad", lambda *a, **k: [], raising=False)
    body = client.get("/teams/basketball/0020500591").json()
    lakers = body["teams"][0]
    assert lakers["team"] == "Los Angeles Lakers" and lakers["squad"]
    assert all("baskets from" in p["headline"] for p in lakers["squad"])
    assert len(lakers["squad"]) <= teams.SQUAD_MAX


def test_every_football_and_basketball_demo_match_has_a_squad_for_each_side(client):
    for m in list_matches():
        if (
            m["sport"] in ("football", "basketball") and m["match_id"] != "7457"
        ):  # Orlando's first game
            body = client.get(f"/teams/{m['sport']}/{m['match_id']}").json()
            assert all(t["squad"] for t in body["teams"]), m["match_id"]


def test_one_of_a_stat_is_singular():
    assert graph._headline(1, "goals", 4) == "1 goal in 4"
    assert graph._headline(1, "points", 2) == "1 point in 2"
    assert graph._headline(1, "runs", 1) == "1 run in 1"
    assert graph._headline(0, "goals", 4) == "0 goals in 4"
    assert graph._headline(3, "goals", 4) == "3 goals in 4"
