"""The graph behind Follow a player (#300): the same players and profiles as the packs, never a
later moment, the packs when the engine fails, and "Also in our library" from a traversal."""

import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient

from core import graph, predict
from core.app import Deps, create_app
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments

MATCHES = [m["match_id"] for m in list_matches()]


def line(m, history):
    return {
        "line_id": f"l{m['idx']}",
        "match_id": m["match_id"],
        "moment_idx": m["idx"],
        "text": "!",
    }


@pytest.fixture
def client(tmp_path):
    deps = Deps(list_matches, load_moments, line)
    with TestClient(create_app(store=Store(tmp_path), deps=deps)) as c:
        yield c


def replayed(client, match_id):
    rid = client.post("/replays", json={"match_id": match_id, "speed": 1e6}).json()["replay_id"]
    read_stream(client, rid)
    return rid


@pytest.mark.parametrize("match_id", MATCHES)
def test_the_graph_answers_like_the_packs(match_id):
    assert graph.start() is not None  # the engine runs here: parity is not tested on a fallback
    moments = load_moments(match_id)
    js, g = predict.load_pack(moments[0]["sport"], match_id), graph.pack(match_id)
    assert list(g["players"]) == list(js["players"])  # order breaks name ties in find()
    for idx in (0, len(moments) // 3, 2 * len(moments) // 3, len(moments) - 1):
        past = moments[: idx + 1]
        assert predict.players(g, past) == predict.players(js, past)
        for name in js["players"]:
            assert predict.profile(g, past, idx, name) == predict.profile(js, past, idx, name)


def test_the_route_reads_the_graph_and_cuts_at_the_moment(client, monkeypatch):
    served = []
    read = graph.pack
    monkeypatch.setattr(graph, "pack", lambda mid: served.append(read(mid)) or served[-1])
    rid = replayed(client, "0020500591")
    url = f"/replays/{rid}/players/kobe/profile"
    early, full = client.get(url, params={"moment_idx": 3}).json(), client.get(url).json()
    assert served and all(served)  # both answers came from the graph, not the fallback
    kobe = [t["idx"] for t in served[0]["tonight"] if t["player"] == "Kobe Bryant"]
    assert max(kobe) > 3  # can go red: the graph holds his later shots too
    assert early["tonight"]["attempts"] == sum(i <= 3 for i in kobe) < full["tonight"]["attempts"]


def test_the_packs_answer_when_the_engine_fails(tmp_path, monkeypatch, caplog):
    rid_url = "/replays/{}/players/Hugo Lloris/profile"
    with TestClient(
        create_app(store=Store(tmp_path), deps=Deps(list_matches, load_moments, line))
    ) as c:
        rid = replayed(c, "3869685")
        on = (c.get(f"/replays/{rid}/players").json(), c.get(rid_url.format(rid)).json())

        class Broken:
            def query(self, *a):
                raise RuntimeError("engine down")

        monkeypatch.setattr(graph, "_db", Broken())
        with caplog.at_level(logging.WARNING, "touchline.graph"):
            off = (c.get(f"/replays/{rid}/players").json(), c.get(rid_url.format(rid)).json())
        assert "RuntimeError" in caplog.text and "engine down" not in caplog.text
    assert on[1].pop("library")  # can go red: the graph added it, the packs can't
    assert off == on

    def no_engine():
        raise ImportError("no wheel")

    monkeypatch.setattr(graph, "_db", None)
    monkeypatch.setattr(graph, "load", no_engine)
    assert graph.start() is None and graph.pack("3869685") is None
    with TestClient(
        create_app(store=Store(tmp_path), deps=Deps(list_matches, load_moments, line))
    ) as c:
        rid = replayed(c, "3869685")
        assert c.get(rid_url.format(rid)).json() == off[1]


def test_missing_sdk_import_keeps_graph_and_profile_routes_on_json_fallback(tmp_path, monkeypatch):
    # Simulate the wheel being absent at import time, rather than only making graph.load fail.
    monkeypatch.setitem(sys.modules, "surrealdb", None)
    monkeypatch.setattr(graph, "_db", None)
    assert graph.start() is None
    assert graph.pack("3869685") is None
    assert graph.library("football", "3869685", "Hugo Lloris") == []

    match_id = "3869685"
    moments = load_moments(match_id)
    pack = predict.load_pack("football", match_id)
    expected_players = predict.players(pack, moments)
    expected_profile = predict.profile(pack, moments, len(moments) - 1, "Hugo Lloris")

    app = create_app(store=Store(tmp_path), deps=Deps(list_matches, load_moments, line))
    with TestClient(app) as c:
        rid = replayed(c, match_id)
        players = c.get(f"/replays/{rid}/players")
        profile = c.get(f"/replays/{rid}/players/Lloris/profile")
        assert players.status_code == profile.status_code == 200
        assert players.json() == expected_players
        assert profile.json() == expected_profile
        assert "library" not in profile.json()


def write_match(tmp, mid, home, away, players, date):
    """A two-team football match: `players` maps name to team."""
    (tmp / "sample").mkdir(exist_ok=True)
    (tmp / "packs").mkdir(exist_ok=True)
    header = {"sport": "football", "match_id": mid, "home": home, "away": away}
    header |= {"competition": "League", "stage": "Round 1", "date": date}
    (tmp / "sample" / f"football-{mid}.json").write_text(json.dumps({"header": header}))
    record = {"games": 1, "attempts": 0, "made": 0, "xg": 0, "zones": {}}
    pack = {
        "match_id": mid,
        "sport": "football",
        "window": {"from": "2020-01-01", "to": "2020-06-01"},
        "players": {n: {"team": t, **record} for n, t in players.items()},
        "teams": {home: {"attempts": 0, "made": 0}, away: {"attempts": 0, "made": 0}},
        "tonight": [],
    }
    (tmp / "packs" / f"football-{mid}.json").write_text(json.dumps(pack))


def test_also_in_our_library_walks_the_graph(tmp_path, monkeypatch):
    write_match(
        tmp_path, "1", "Reds", "Blues", {"Ann": "Reds", "Bea": "Reds", "Cy": "Blues"}, "2020-02-01"
    )
    write_match(
        tmp_path,
        "2",
        "Greens",
        "Reds",
        {"Ann": "Greens", "Di": "Greens", "Bea": "Reds"},
        "2020-03-01",
    )
    write_match(tmp_path, "3", "Golds", "Blues", {"Ann": "Golds", "Cy": "Blues"}, "2020-01-01")
    monkeypatch.setattr(graph, "_db", graph.load(tmp_path / "packs", tmp_path / "sample"))
    also = graph.library("football", "1", "Ann")
    assert [(m["match_id"], m["team"], m["teammates"]) for m in also] == [
        ("3", "Golds", []),
        ("2", "Greens", ["Di"]),  # Bea played that match for the other side: not a teammate
    ]  # oldest first, and never match 1, the one on screen
    assert also[1]["title"] == "Greens v Reds, League Round 1" and also[1]["date"] == "2020-03-01"
    assert graph.library("football", "1", "Bea")[0]["teammates"] == []
    assert graph.library("football", "2", "Di") == []  # one match only: the card shows nothing


def test_the_profile_shows_the_library_only_when_there_is_one(client):
    rid = replayed(client, "3869685")
    lloris = client.get(f"/replays/{rid}/players/Lloris/profile").json()["library"]
    assert [m["match_id"] for m in lloris] == ["3754092"]
    assert lloris[0]["team"] == "Tottenham Hotspur" and "Harry Kane" in lloris[0]["teammates"]
    assert "library" not in client.get(f"/replays/{rid}/players/Messi/profile").json()
