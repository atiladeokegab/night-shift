"""The long tail (#189): a Women's Super League match, bundled and mapped like the famous ones."""

from agent import feed
from core import insight
from core.predict import load_pack
from data.matches import PEAKS, list_matches, load_moments, match_header, video_map

WSL = "3913122"  # Brighton 3-2 Bristol City, 21 Jan 2024


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
    assert (vmap["youtube_id"], vmap["start"]) == ("soJej-DhVe0", 29)
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
