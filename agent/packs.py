"""Pre-match player packs (#118): `uv run python -m agent.packs` writes data/packs/*.json.

A pack holds only the players and teams in the match, and only their shots from earlier in the same
season or tournament, up to the day before the match. `tonight` is the match's own shots, each
linked to the sample moment that reveals it, so runtime filters to idx <= the current moment.
Built offline from the feed's caches and committed, so runtime needs no network.
"""

from __future__ import annotations

import csv
import io
import json
import tarfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import httpx

from agent import feed

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "data" / "packs"
SAMPLE = ROOT / "data" / "sample"
SHOT_CAP = 300  # each player's most recent pre-match shots on the map; totals and zones count all

# match -> its source: shufinskiy/nba_data shot archives (the regular-season file has no playoffs),
# or a StatsBomb (competition, season)
MATCHES = {
    ("basketball", "0020500591"): ("shotdetail_2005",),
    ("basketball", "0049700088"): ("shotdetail_1997", "shotdetail_po_1997"),
    ("football", "3869685"): (43, 106),
}


def _tally(players: dict, teams: dict, shots: list, games: dict) -> None:
    """Add (player, team, shot) rows, oldest first; games is player -> the games they played."""
    for name, team, shot in shots:
        if team in teams:  # a player traded in mid-season brings their shots, not old team totals
            teams[team]["attempts"] += 1
            teams[team]["made"] += shot["made"]
        if name not in players:
            continue
        p = players[name]
        p["attempts"] += 1
        p["made"] += shot["made"]
        zone = p["zones"].setdefault(shot["zone"], {"att": 0, "made": 0})
        zone["att"] += 1
        zone["made"] += shot["made"]
        if "xg" in shot:
            p["xg"] += shot["xg"]
        p["shots"].append(shot)
    for name, p in players.items():
        p["games"] = len(games.get(name, ()))
        p["shots"] = p["shots"][-SHOT_CAP:]
        if "xg" in p:
            p["xg"] = round(p["xg"], 2)


def _pack(header: dict, source: str, coords: str, start: str, players, teams, tonight) -> dict:
    day_before = (date.fromisoformat(header["date"]) - timedelta(days=1)).isoformat()
    return {
        "match_id": header["match_id"],
        "sport": header["sport"],
        "source": source,
        "window": {"from": start, "to": day_before},
        "coords": coords,
        "players": players,
        "teams": teams,
        "tonight": tonight,
    }


# --- basketball ---------------------------------------------------------------------------


def nba_shots(name: str) -> list[dict]:
    """shotchartdetail rows for one season archive, from the mirror the feed uses."""
    timeout = httpx.Timeout(120.0, connect=10.0)
    data = feed._fetch(feed.NBA_PBP.format(name=name), f"{name}.tar.xz", timeout=timeout)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
        member = next(m for m in tar.getmembers() if m.isfile() and m.name.endswith(".csv"))
        return list(csv.DictReader(io.TextIOWrapper(tar.extractfile(member), encoding="utf-8")))


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _nba_shot(r: dict) -> dict:
    return {
        "x": int(r["LOC_X"]),
        "y": int(r["LOC_Y"]),
        "made": r["SHOT_MADE_FLAG"] == "1",
        "zone": feed._s(r["SHOT_ZONE_BASIC"]),
    }


def basketball_pack(match_id: str, sample: dict, archives: tuple) -> dict:
    header, moments = sample["header"], sample["moments"]
    rows = feed.nba_rows(match_id)
    if len(feed.basketball_moments(header, rows)) != len(moments):
        raise ValueError(f"{match_id}: the sample is stale against the play-by-play")
    # the moment each play-by-play row is revealed by: the first moment at or after it (a pad row
    # keeps the last period, so a prefix never mistakes an earlier period's end for the final one)
    pad = [{"PERIOD": str(max(feed._int(r.get("PERIOD")) for r in rows))}]
    reveal = {
        r["EVENTNUM"]: len(feed.basketball_moments(header, rows[:i] + pad))
        for i, r in enumerate(rows)
    }
    # the match's players by NBA id, named and teamed as the feed names them
    roster = {}
    for r in rows:
        for n in (1, 2, 3):
            team, name = feed._team(r, n), feed._s(r.get(f"PLAYER{n}_NAME"))
            if team in (header["home"], header["away"]) and name:
                roster[r[f"PLAYER{n}_ID"]] = (name, team)

    shots = sorted(
        (r for a in archives for r in nba_shots(a)),
        key=lambda r: (r["GAME_DATE"], r["GAME_ID"], feed._int(r["GAME_EVENT_ID"])),
    )
    want = str(int(match_id))
    tonight_rows = [r for r in shots if r["GAME_ID"] == want]
    team_ids = {r["TEAM_ID"]: feed._s(r["TEAM_NAME"]) for r in tonight_rows}
    before = [r for r in shots if _iso(r["GAME_DATE"]) < header["date"]]

    players = {
        name: {"team": team, "games": 0, "attempts": 0, "made": 0, "zones": {}, "shots": []}
        for name, team in roster.values()
    }
    teams = {name: {"attempts": 0, "made": 0} for name in team_ids.values()}
    games = defaultdict(set)
    rows_in = []
    for r in before:
        team = team_ids.get(r["TEAM_ID"])
        name = roster.get(r["PLAYER_ID"], ("", ""))[0]
        if team or name:
            games[name].add(r["GAME_ID"])
            rows_in.append((name, team, {**_nba_shot(r), "date": _iso(r["GAME_DATE"])}))
    _tally(players, teams, rows_in, games)

    tonight = [
        {"idx": reveal[r["GAME_EVENT_ID"]], "player": roster[r["PLAYER_ID"]][0], **_nba_shot(r)}
        for r in tonight_rows
    ]
    archive = " + ".join(archives)
    start = _iso(min(r["GAME_DATE"] for r in shots))
    source = f"stats.nba.com shotchartdetail via shufinskiy/nba_data {archive}"
    return _pack(header, source, "nba_loc_tenths_ft", start, players, teams, tonight)


# --- football -----------------------------------------------------------------------------


def football_zone(x: float, y: float) -> str:
    """StatsBomb 120x80, attacking towards x=120."""
    if x >= 114 and 30 <= y <= 50:
        return "six-yard box"
    if x >= 102 and 18 <= y <= 62:
        return "central box" if 30 <= y <= 50 else "wide box"
    return "outside box"


def _sb_shot(x: float, y: float, made: bool, xg) -> dict:
    return {"x": x, "y": y, "made": made, "zone": football_zone(x, y), "xg": round(xg or 0.0, 2)}


def football_pack(match_id: str, sample: dict, comp_season: tuple) -> dict:
    header, moments = sample["header"], sample["moments"]
    nicknames = feed.statsbomb_nicknames(match_id)
    lineups = json.loads((feed.CACHE / f"sb_l_{match_id}.json").read_bytes())
    ids, names = {}, {}  # player id -> team, and the name the sample's moments use (feed's who())
    for t in lineups:
        for p in t.get("lineup") or []:
            ids[p["player_id"]] = feed._side(t["team_name"])
            names[p["player_id"]] = nicknames.get(p["player_id"], feed._s(p["player_name"]))
    players = {
        names[pid]: {
            "team": team,
            "games": 0,
            "attempts": 0,
            "made": 0,
            "xg": 0.0,
            "zones": {},
            "shots": [],
        }
        for pid, team in ids.items()
    }
    teams = {header["home"]: {"attempts": 0, "made": 0}, header["away"]: {"attempts": 0, "made": 0}}

    earlier = sorted(
        (
            m
            for m in feed.statsbomb_matches(*comp_season)
            if m["match_date"] < header["date"]
            and {
                feed._side(m["home_team"]["home_team_name"]),
                feed._side(m["away_team"]["away_team_name"]),
            }
            & set(teams)
        ),
        key=lambda m: m["match_date"],
    )
    games, rows_in = defaultdict(set), []
    for m in earlier:
        for ev in feed.statsbomb_events(str(m["match_id"])):
            pid = (ev.get("player") or {}).get("id")
            if pid in ids:
                games[names[pid]].add(m["match_id"])
            team = feed._side(feed._name(ev.get("team")))
            # shootout kicks (period 5) are not chances: they stay out of the pre-match rates
            if feed._name(ev.get("type")) != "Shot" or team not in teams or ev.get("period") == 5:
                continue
            shot = ev.get("shot") or {}
            x, y = ev["location"][:2]
            made = feed._name(shot.get("outcome")) == "Goal"
            name = names.get(pid, "")
            row = {**_sb_shot(x, y, made, shot.get("statsbomb_xg")), "date": m["match_date"]}
            rows_in.append((name, team, row))
    _tally(players, teams, rows_in, games)

    tonight = [
        {
            "idx": m["idx"],
            "player": m["players"]["shooter"],
            **_sb_shot(m["x"], m["y"], m["outcome"] == "Goal", m["detail"].get("xg")),
        }
        for m in moments
        if m["type"] == "Shot"
    ]
    start = min(m["match_date"] for m in feed.statsbomb_matches(*comp_season))
    source = f"StatsBomb open data, competition {comp_season[0]} season {comp_season[1]}"
    return _pack(header, source, "statsbomb_120x80", start, players, teams, tonight)


def build(sport: str, match_id: str) -> dict:
    sample = json.loads((SAMPLE / f"{sport}-{match_id}.json").read_text())
    make = basketball_pack if sport == "basketball" else football_pack
    return make(match_id, sample, MATCHES[(sport, match_id)])


def main() -> None:
    PACKS.mkdir(parents=True, exist_ok=True)
    for sport, match_id in MATCHES:
        pack = build(sport, match_id)
        path = PACKS / f"{sport}-{match_id}.json"
        path.write_text(json.dumps(pack, ensure_ascii=False, separators=(",", ":")) + "\n")
        size = path.stat().st_size
        print(f"{path.name}: {len(pack['players'])} players, {size / 1e3:.0f} kB")


if __name__ == "__main__":
    main()
