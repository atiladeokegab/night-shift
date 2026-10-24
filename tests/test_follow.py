"""Follow a player (#140): GET /replays/{id}/players and .../players/{name}/profile answer from the
real packs for every match, and the profile never uses a moment after the one on screen."""

import copy

import pytest
from fastapi.testclient import TestClient

from core import predict
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


@pytest.mark.parametrize(
    ("match_id", "who"),
    [("0020500591", "Kobe"), ("3869685", "Messi"), ("1298150", "Kohli"), ("3754092", "Kane")],
)
def test_a_later_moment_never_reaches_the_profile(match_id, who):
    moments = load_moments(match_id)
    pack = predict.load_pack(moments[0]["sport"], match_id)
    name, idx = predict.find(pack, who), len(moments) // 2

    def plus_one_at(i):  # a made shot (or a six) by the player at moment i, marked to show if used
        more = copy.deepcopy(pack)
        t = copy.deepcopy(pack["tonight"][0])
        t.update(idx=i, made=True, xg=0.99, runs=6, out="", zone="marked")
        t["player" if "player" in t else "batter"] = name
        more["tonight"].append(t)
        return predict.profile(more, moments, idx, name)

    now = predict.profile(pack, moments, idx, name)
    assert plus_one_at(moments[idx]["idx"] + 1) == now
    assert (
        plus_one_at(moments[idx]["idx"]) != now
    )  # the same shot on screen counts: this can go red


def test_f1_positions_stop_at_the_moment_on_screen():
    moments = load_moments("9636")
    pack = predict.load_pack("f1", "9636")
    early = predict.profile(pack, moments, 6, "Max Verstappen")["tonight"]["laps"]
    late = predict.profile(pack, moments, len(moments) - 1, "Max Verstappen")["tonight"]["laps"]
    assert max(lap["lap"] for lap in early) == moments[6]["score"]["lap"]
    assert late[-1] == {"lap": 69, "pos": 1} and len(late) > len(early)


def test_the_route_cuts_tonight_at_moment_idx(client):
    rid = replayed(client, "0020500591")
    url = f"/replays/{rid}/players/kobe/profile"
    early = client.get(url, params={"moment_idx": 3}).json()
    full = client.get(url).json()
    tonight = predict.load_pack("basketball", "0020500591")["tonight"]
    kobe = [t["idx"] for t in tonight if t["player"] == "Kobe Bryant"]
    assert max(kobe) > 3  # the test can go red: tonight holds his shots after the cut
    assert early["tonight"]["attempts"] == sum(i <= 3 for i in kobe) < full["tonight"]["attempts"]
    assert full["tonight"]["attempts"] == len(kobe)


@pytest.mark.parametrize("match_id", MATCHES)
def test_every_player_lists_and_profiles(client, match_id):
    rid = replayed(client, match_id)
    listed = client.get(f"/replays/{rid}/players").json()
    pack = predict.load_pack(load_moments(match_id)[0]["sport"], match_id)
    assert {p["name"] for p in listed} >= set(pack["players"])
    named = [p["named"] for p in listed]
    assert any(named) and named == sorted(named, reverse=True)  # named in the moments first
    for p in listed:
        got = client.get(f"/replays/{rid}/players/{p['name']}/profile")
        assert got.status_code == 200, p
        body = got.json()
        assert body["player"] == p["name"] and body["text"]
        assert (body["before"] is not None) == p["record"]
        assert body["small_sample"] == (body["n"] < predict.SMALL)


def test_accents_and_initials_resolve(client):
    rid = replayed(client, "3869685")
    assert client.get(f"/replays/{rid}/players/mbappe/profile").json()["player"] == "Kylian Mbappé"
    rid = replayed(client, "1298150")
    assert client.get(f"/replays/{rid}/players/Virat Kohli/profile").json()["player"] == "V Kohli"


def test_unknown_replay_or_player(client):
    assert client.get("/replays/nope/players").status_code == 404
    assert client.get("/replays/nope/players/Kobe/profile").status_code == 404
    rid = replayed(client, "0020500591")
    assert client.get(f"/replays/{rid}/players/Nobody/profile").status_code == 404
