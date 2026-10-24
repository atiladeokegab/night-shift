"""The shot map's route (#120): GET /replays/{id}/players/{name}/shots answers from the real
pre-match packs (#118), and never shows a shot from after the moment on screen."""

import threading

import pytest
from fastapi.testclient import TestClient

from core.app import Deps, create_app
from core.predict import load_pack
from core.smoke import read_stream
from core.store import Store
from data.matches import list_matches, load_moments

STARS = [
    ("0020500591", "Kobe Bryant"),
    ("0049700088", "Michael Jordan"),
    ("3869685", "Lionel Messi"),
]


def line(m, history):
    return {
        "line_id": f"l{m['idx']}",
        "match_id": m["match_id"],
        "moment_idx": m["idx"],
        "text": "!",
    }


def client_for(tmp_path, commentate=line):
    deps = Deps(list_matches, load_moments, commentate)
    return TestClient(create_app(store=Store(tmp_path), deps=deps))


def later_cut(match_id, name):
    """A moment with some of the player's shots at or before it and some after."""
    sport = load_moments(match_id)[0]["sport"]
    idxs = sorted(t["idx"] for t in load_pack(sport, match_id)["tonight"] if t["player"] == name)
    cut = next(i for i in idxs if i < idxs[-1])
    return cut, idxs


@pytest.mark.parametrize(("match_id", "name"), STARS)
def test_kobe_jordan_and_messi_each_get_a_map(tmp_path, match_id, name):
    with client_for(tmp_path) as client:
        rid = client.post("/replays", json={"match_id": match_id, "speed": 1e6}).json()["replay_id"]
        read_stream(client, rid)
        got = client.get(f"/replays/{rid}/players/{name}/shots").json()
    assert got["player"] == name and got["sport"] in ("basketball", "football")
    assert got["season"] and got["tonight"] and got["zones"]
    assert {"x", "y", "made"} <= got["season"][0].keys() <= {"x", "y", "made", "zone"}
    assert all(0 <= z["rate"] <= 1 for z in got["zones"])


@pytest.mark.parametrize(("match_id", "name"), STARS)
def test_a_later_shot_never_shows(tmp_path, match_id, name):
    cut, idxs = later_cut(match_id, name)
    assert idxs[-1] > cut  # the test can go red: tonight holds shots after the cut
    with client_for(tmp_path) as client:
        rid = client.post("/replays", json={"match_id": match_id, "speed": 1e6}).json()["replay_id"]
        read_stream(client, rid)
        url = f"/replays/{rid}/players/{name}/shots"
        on_screen = client.get(url, params={"moment_idx": cut}).json()["tonight"]
        full = client.get(url).json()["tonight"]
    assert on_screen and max(t["idx"] for t in on_screen) <= cut
    assert len(on_screen) == sum(i <= cut for i in idxs)
    assert max(t["idx"] for t in full) == idxs[-1]


def test_the_page_cannot_ask_past_the_last_moment_sent(tmp_path):
    match_id, name = STARS[0]
    cut, _ = later_cut(match_id, name)
    hold, held = threading.Event(), threading.Event()

    def stalls(m, history):  # the commentator is still working on moment `cut`
        if m["idx"] == cut:
            held.set()
            hold.wait(10)
        return line(m, history)

    with client_for(tmp_path, stalls) as client:
        rid = client.post("/replays", json={"match_id": match_id, "speed": 1e6}).json()["replay_id"]
        assert held.wait(10)
        url = f"/replays/{rid}/players/{name}/shots"
        got = client.get(url, params={"moment_idx": 10_000}).json()["tonight"]
        hold.set()
    assert got and max(t["idx"] for t in got) <= cut


def test_no_map_without_a_pack_a_player_or_a_moment(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get("/replays/nope/players/Kobe Bryant/shots").status_code == 404
        rid = client.post("/replays", json={"match_id": "1298150", "speed": 1e6}).json()
        rid = rid["replay_id"]
        read_stream(client, rid)
        assert client.get(f"/replays/{rid}/players/Virat Kohli/shots").status_code == 404  # cricket
        rid = client.post("/replays", json={"match_id": "0020500591", "speed": 1e6}).json()
        rid = rid["replay_id"]
        read_stream(client, rid)
        assert client.get(f"/replays/{rid}/players/Nobody/shots").status_code == 404
