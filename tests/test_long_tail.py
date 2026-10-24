"""The long tail (#189): a Women's Super League match, bundled and mapped like the famous ones;
and (#246) an NWSL match and a women's T20 with no video, each called whole."""

import pytest
from fastapi.testclient import TestClient

from agent import feed
from core import insight
from core.app import Deps, create_app
from core.predict import load_pack
from core.smoke import read_stream
from core.store import Store
from data.matches import PEAKS, list_matches, load_moments, match_header, video_map

WSL = "3913122"  # Brighton 3-2 Bristol City, 21 Jan 2024
NWSL = "7457"  # Orlando Pride 3-4 North Carolina Courage, 24 May 2018
T20 = "1515217"  # Netherlands v Nepal, Women's T20 World Cup Qualifier, 22 Jan 2026


def test_the_wsl_match_loads_with_its_five_goals_and_late_winner():
    header, moments = match_header(WSL), load_moments(WSL)
    assert (header["home"], header["away"], header["competition"]) == (
        "Brighton & Hove Albion WFC",
        "Bristol City WFC",
        "FA Women's Super League",
    )
    goals = [
        (m["idx"], m["clock"], m["players"]["shooter"], m["score"]["home"], m["score"]["away"])
        for m in moments
        if m["outcome"] == "Goal"
    ]
    assert goals == [
        (8, "30:57", "Elisabeth Terland", 1, 0),
        (18, "54:22", "Abigail Harrison", 1, 1),
        (19, "56:02", "Katie Robinson", 2, 1),
        (33, "82:34", "Carrie Jones", 2, 2),
        (34, "94:48", "Elisabeth Terland", 3, 2),
    ]
    assert ("football", WSL) in feed.DEMO and WSL in {m["match_id"] for m in list_matches()}


def test_every_goal_is_on_the_official_highlights_and_the_jump_plays_the_last_two():
    vmap = video_map(WSL)
    mapped = {m["idx"]: m["video_t"] for m in vmap["moments"]}
    # Timed against the score bug in Brighton's own upload: it turns 1-0, 1-1, 2-1, 2-2, 3-2 then.
    assert {i: mapped.get(i) for i in (8, 18, 19, 33, 34)} == {
        8: 39.0,
        18: 108.5,
        19: 141.0,
        33: 171.0,
        34: 201.0,
    }
    assert (vmap["youtube_id"], vmap["start"]) == ("soJej-DhVe0", 14)
    assert PEAKS[WSL] == 33 and video_map(WSL, PEAKS[WSL])["start"] == 161


def test_the_checks_hold_on_its_moments():
    header, moments = match_header(WSL), load_moments(WSL)
    assert all(("where" in m["detail"]) == ("x" in m) for m in moments)
    winner = moments[34]
    assert winner["detail"]["where"] == "from 10 yards, central"
    said = "Terland, on the half volley from ten yards! Brighton lead three-two!"
    assert insight.wrong_numbers(said, winner, header) == []
    assert insight.wrong_numbers("Terland! Brighton lead 4-2!", winner, header) == [
        "4 is not in the moment"
    ]
    # Who leads (#185), by the names a line uses: "Brighton", not "Brighton & Hove Albion WFC".
    equaliser = moments[33]
    assert insight.wrong_numbers("Brighton take the lead!", equaliser, header) == [
        "Brighton & Hove Albion WFC do not lead"
    ]
    assert insight.wrong_numbers("Bristol City lead three-two!", winner, header) == [
        "Bristol City WFC do not lead"
    ]
    derby = {"home": "Manchester City", "away": "Manchester United"}
    assert "manchester" not in insight._sides(derby)[0]  # names neither side
    facts = insight._profiles(load_pack("football", WSL), moments[:20])
    assert facts and all("this season before tonight" in d for d in facts if "before" in d)


def test_the_spoken_lead_and_where_say_the_club_not_its_wfc_suffix():
    moments = load_moments(WSL)
    assert moments[8]["detail"]["lead"] == "Brighton & Hove Albion lead 1-0"
    stated = [str(m["detail"].get(k, "")) for m in moments for k in ("lead", "where")]
    assert not any("WFC" in s for s in stated)
    assert any("Bristol City's" in s for s in stated)


def test_the_nwsl_match_is_whole_seven_goals_and_a_late_own_goal_winner():
    header, moments = match_header(NWSL), load_moments(NWSL)
    assert (header["home"], header["away"], header["competition"], header["date"]) == (
        "Orlando Pride",
        "North Carolina Courage",
        "NWSL",
        "2018-05-24",
    )
    goals = [
        (m["idx"], m["clock"], m["score"]["home"], m["score"]["away"])
        for m in moments
        if m["outcome"] in ("Goal", "Own goal")
    ]
    assert goals[-2:] == [(38, "82:12", 3, 3), (41, "89:13", 3, 4)] and len(goals) == 7
    match = next(m for m in list_matches() if m["match_id"] == NWSL)
    assert "youtube_id" not in match and video_map(NWSL) is None  # no highlights limit the calls
    assert ("football", NWSL) in feed.DEMO and load_pack("football", NWSL)["players"]


def test_the_womens_t20_is_whole_and_nepal_fall_two_short_off_the_last_ball():
    header, moments = match_header(T20), load_moments(T20)
    assert (header["home"], header["away"], header["date"]) == (
        "Netherlands",
        "Nepal",
        "2026-01-22",
    )
    last = moments[-1]
    assert (last["clock"], last["outcome"], last["score"]["runs"], last["score"]["target"]) == (
        "19.6",
        "4 runs",
        138,
        141,
    )
    assert last["detail"]["chase"] == "Netherlands win by 2 runs"
    assert video_map(T20) is None and ("cricket", T20) in feed.DEMO
    assert load_pack("cricket", T20)["players"]


@pytest.mark.parametrize("match_id", [NWSL, T20])
def test_a_whole_match_calls_every_moment_from_start_to_finish(tmp_path, match_id):
    called = []

    def commentate(moment, history):
        called.append(moment["idx"])
        return {
            "line_id": f"n-{moment['idx']}",
            "match_id": match_id,
            "moment_idx": moment["idx"],
            "text": "Call.",
        }

    deps = Deps(list_matches, load_moments, commentate, video_map)
    with TestClient(create_app(Store(tmp_path), deps)) as client:
        rid = client.post("/replays", json={"match_id": match_id, "speed": 1e6}).json()["replay_id"]
        events = read_stream(client, rid)
    # each in order (the check may ask again for a moment), none left out: no video map skips one
    assert list(dict.fromkeys(called)) == [m["idx"] for m in load_moments(match_id)]
    assert [n for n, _ in events].count("moment") == len(load_moments(match_id))
    assert events[-1][0] == "end" and "error" not in [n for n, _ in events]
