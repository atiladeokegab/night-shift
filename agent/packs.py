"""Pre-match player packs (#118): `uv run python -m agent.packs` writes data/packs/*.json.

A pack holds only the players and teams in the match, and only their shots from earlier in the same
season or tournament, up to the day before the match. `tonight` is the match's own shots, each
linked to the sample moment that reveals it, so runtime filters to idx <= the current moment.
Cricket has no shots: its players carry batting by phase and bowling, and `tonight` is every ball.
F1 has neither: each driver carries their earlier races' grid and finish, and `tonight` is empty.
Built offline from the feed's caches and committed, so runtime needs no network.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import sys
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
# a StatsBomb (competition, season), the year of Cricsheet T20Is, or the year of OpenF1 races
MATCHES = {
    ("basketball", "0020500591"): ("shotdetail_2005",),
    ("basketball", "0049700088"): ("shotdetail_1997", "shotdetail_po_1997"),
    ("football", "3869685"): (43, 106),
    ("football", "3754092"): (2, 27),  # Premier League 2015/16
    ("football", "3913122"): (37, 281),  # FA Women's Super League 2023/24
    ("football", "7457"): (49, 3),  # NWSL 2018
    ("cricket", "1298150"): ("2022",),
    ("cricket", "1515217"): ("2026",),  # Netherlands v Nepal, women's T20I
    ("f1", "9636"): (2024,),
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
        return list(csv.DictReader(io.TextIOWrapper(feed._csv(tar, name), encoding="utf-8")))


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


# --- cricket ------------------------------------------------------------------------------

NOT_BOWLERS = {"run out", "retired hurt", "retired out", "obstructing the field"}


def phase(over: int) -> str:
    return "powerplay" if over < 6 else "middle" if over < 15 else "death"


def _balls(match: dict):
    """(innings no, over, delivery) in the feed's order: super overs are not moments."""
    for n, inn in enumerate(match.get("innings") or [], start=1):
        if isinstance(inn, dict) and not inn.get("super_over"):  # junk skipped as the feed skips it
            for over in inn.get("overs") or []:
                for d in over.get("deliveries") or [] if isinstance(over, dict) else []:
                    if isinstance(d, dict):
                        yield n, inn.get("team"), feed._num(over.get("over")) or 0, d


def _batting(p: dict, over: int) -> dict:
    return p["batting"].setdefault(phase(over), {"balls": 0, "runs": 0, "outs": 0})


def cricket_pack(match_id: str, sample: dict, season: tuple) -> dict:
    header, moments = sample["header"], sample["moments"]
    archive = feed.cricsheet_zip()
    match = feed.cricsheet_match(match_id, archive)
    if len(feed.cricket_moments(header, match)) != len(moments):
        raise ValueError(f"{match_id}: the sample is stale against Cricsheet")
    info = match["info"]
    reg = info["registry"]["people"]
    ids = {
        reg[name]: (feed._s(name), feed._s(t))
        for t, names in info["players"].items()
        for name in names
    }
    players = {
        name: {
            "team": team,
            "games": 0,
            "batting": {},
            "bowling": {"balls": 0, "runs": 0, "wickets": 0},
        }
        for name, team in ids.values()
    }
    teams = {feed._s(t): {"innings": 0, "balls": 0, "runs": 0, "wickets": 0} for t in info["teams"]}

    earlier = []
    for n in archive.namelist():
        if not n.endswith(".json") or n == f"{match_id}.json":
            continue
        m = json.loads(archive.read(n))
        i = m.get("info") or {}
        day = feed._s((i.get("dates") or [""])[0], 10)
        if (
            i.get("gender") == info.get("gender")
            and day.startswith(season[0])
            and day < header["date"]
        ):
            if set(feed._s(t) for t in i.get("teams") or []) & set(teams):
                earlier.append((day, m))
    earlier.sort(key=lambda x: x[0])
    for _, m in earlier:
        people = (m["info"].get("registry") or {}).get("people") or {}
        here = {ids[people[name]][0] for name in people if people[name] in ids}
        for name in here:
            players[name]["games"] += 1
        innings = set()
        for n, team, over, d in _balls(m):
            team, extras, runs = feed._s(team), d.get("extras") or {}, d.get("runs") or {}
            outs = [w for w in d.get("wickets") or [] if isinstance(w, dict)]
            legal = not (extras.get("wides") or extras.get("noballs"))
            if team in teams:
                innings.add((team, n))
                teams[team]["balls"] += legal
                teams[team]["runs"] += feed._num(runs.get("total")) or 0
                teams[team]["wickets"] += len(outs)
            batter = ids.get(people.get(d.get("batter")), ("",))[0]
            if batter and not extras.get("wides"):  # a wide is not a ball faced
                _batting(players[batter], over)["balls"] += 1
                _batting(players[batter], over)["runs"] += feed._num(runs.get("batter")) or 0
            for w in outs:
                out = ids.get(people.get(w.get("player_out")), ("",))[0]
                if out:
                    _batting(players[out], over)["outs"] += 1
            bowler = ids.get(people.get(d.get("bowler")), ("",))[0]
            if bowler:
                b = players[bowler]["bowling"]
                b["balls"] += legal
                b["runs"] += (
                    (feed._num(runs.get("total")) or 0)
                    - (extras.get("byes") or 0)
                    - (extras.get("legbyes") or 0)
                )
                b["wickets"] += sum(w.get("kind") not in NOT_BOWLERS for w in outs)
        for team, _ in innings:
            teams[team]["innings"] += 1
    for p in players.values():
        for ph in p["batting"].values():
            ph["sr"] = round(100 * ph["runs"] / ph["balls"], 1) if ph["balls"] else None
            ph["out_rate"] = round(ph["outs"] / ph["balls"], 3) if ph["balls"] else None
        b = p["bowling"]
        b["economy"] = round(6 * b["runs"] / b["balls"], 2) if b["balls"] else None

    # the moment each ball is revealed by: tag every ball's clock on a copy, read the tags back
    tagged = copy.deepcopy(match)
    for k, (*_, d) in enumerate(_balls(tagged)):
        d["actual_delivery"] = str(k)
    shown = [int(m["clock"]) for m in feed.cricket_moments(header, tagged)]
    tonight = []
    for k, (n, _, over, d) in enumerate(_balls(match)):
        out = next((w.get("player_out") for w in d.get("wickets") or [] if isinstance(w, dict)), "")
        tonight.append(
            {
                "idx": next(i for i, b in enumerate(shown) if b >= k),
                "innings": n,
                "over": over,
                "phase": phase(over),
                "batter": feed._s(d.get("batter")),
                "bowler": feed._s(d.get("bowler")),
                "runs": feed._num((d.get("runs") or {}).get("total")) or 0,
                "out": feed._s(out),
            }
        )
    source = f"Cricsheet T20Is, {season[0]}"
    pack = _pack(header, source, None, f"{season[0]}-01-01", players, teams, tonight)
    # no shots to date, so the pre-match matches themselves, for the look-ahead check
    pack["matches"] = [{"date": day, "teams": m["info"]["teams"]} for day, m in earlier]
    return pack


# --- f1 -----------------------------------------------------------------------------------


def f1_pack(match_id: str, sample: dict, season: tuple) -> dict:
    """Each driver's races earlier in the season: grid (their first position row), finish (the
    classified result, none for a DNF, DNS or DSQ), and from those the averages and wins."""
    header = sample["header"]

    def drivers(key: str) -> dict:
        """Car number -> (name as the feed names them, team) in one session."""
        return {
            d["driver_number"]: (
                feed._s(f"{d['first_name']} {d['last_name']}"),
                feed._s(d["team_name"]),
            )
            for d in feed.openf1("drivers", key)
        }

    players = {
        name: {"team": team, "games": 0, "results": []} for name, team in drivers(match_id).values()
    }
    url = f"{feed.OPENF1}/sessions?year={season[0]}&session_name=Race"
    races = sorted(
        (
            s
            for s in json.loads(feed._fetch(url, f"of1_sessions_{season[0]}_race.json"))
            if s["date_start"][:10] < header["date"] and not s.get("is_cancelled")
        ),
        key=lambda s: s["date_start"],
    )
    for s in races:
        key = str(s["session_key"])
        grid = {}
        for r in sorted(feed.openf1("position", key), key=lambda r: r["date"]):
            grid.setdefault(r["driver_number"], r["position"])
        # by name, not number: a reserve can race under another number for another team
        names = {n: name for n, (name, _) in drivers(key).items()}
        for r in feed.openf1("session_result", key):
            if names.get(r["driver_number"]) not in players:
                continue
            out = r.get("dnf") or r.get("dns") or r.get("dsq")
            p = players[names[r["driver_number"]]]
            p["games"] += 1
            p["results"].append(
                {
                    "date": s["date_start"][:10],
                    "race": feed._s(s["location"]),
                    "grid": grid.get(r["driver_number"]),
                    "finish": None if out else r["position"],
                }
            )
    for p in players.values():
        done = [r for r in p["results"] if r["finish"]]
        both = [r for r in done if r["grid"]]
        p["finishes"] = len(done)
        p["avg_finish"] = round(sum(r["finish"] for r in done) / len(done), 1) if done else None
        p["avg_gained"] = (
            round(sum(r["grid"] - r["finish"] for r in both) / len(both), 1) if both else None
        )
        p["wins"] = sum(r["finish"] == 1 for r in done)
    source = f"OpenF1 {season[0]} races"
    return _pack(header, source, None, races[0]["date_start"][:10], players, {}, [])


def build(sport: str, match_id: str) -> dict:
    sample = json.loads((SAMPLE / f"{sport}-{match_id}.json").read_text())
    make = {
        "basketball": basketball_pack,
        "football": football_pack,
        "cricket": cricket_pack,
        "f1": f1_pack,
    }[sport]
    return make(match_id, sample, MATCHES[(sport, match_id)])


def main(argv: list[str]) -> None:
    """Every pack, or only the one named: `python -m agent.packs football 3754092`."""
    PACKS.mkdir(parents=True, exist_ok=True)
    for sport, match_id in [tuple(argv)] if argv else MATCHES:
        pack = build(sport, match_id)
        path = PACKS / f"{sport}-{match_id}.json"
        path.write_text(json.dumps(pack, ensure_ascii=False, separators=(",", ":")) + "\n")
        size = path.stat().st_size
        print(f"{path.name}: {len(pack['players'])} players, {size / 1e3:.0f} kB")


if __name__ == "__main__":
    main(sys.argv[1:])
