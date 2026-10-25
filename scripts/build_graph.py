"""Build data/graph: every team and player of each sample match's competition and season, on disk.

    uv run python scripts/build_graph.py [football]

Offline, like agent/packs.py: it reuses agent/feed.py's names and URLs, streams every match of the
competition-season (nothing is cached, raw events are dropped after each match) and writes
SurrealDB's embedded surrealkv store to data/graph, shipped in the image. Two tables:

    fixture     one per match: sport, competition, season, start (ISO kickoff), home, away, score
    appearance  one per player, team and season: its games as [start, minutes, *totals]
"""

import csv
import io
import json
import shutil
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from agent import feed
from agent.packs import MATCHES, NOT_BOWLERS

GRAPH = Path(__file__).resolve().parent.parent / "data" / "graph"


def _get(url: str):
    for attempt in range(4):
        try:
            r = httpx.get(url, timeout=feed.TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def _clock(t) -> int:
    return int(t.split(":")[0]) if t else 0


def football_match(m: dict) -> tuple[dict, list[dict]]:
    """One StatsBomb match as a fixture and its players' appearances."""
    mid = str(m["match_id"])
    events = _get(f"{feed.STATSBOMB}/events/{mid}.json")
    lineups = _get(f"{feed.STATSBOMB}/lineups/{mid}.json")
    nick = {
        p["player_id"]: feed._s(p["player_nickname"])
        for t in lineups
        for p in t.get("lineup") or []
        if feed._s(p.get("player_nickname"))
    } | feed.NAME_OVERRIDES
    end = max((e.get("minute", 0) for e in events if e.get("period", 1) < 5), default=90)
    home, away = (feed._side(m[k][f"{k}_name"]) for k in ("home_team", "away_team"))
    # shortcut: StatsBomb's kick_off is the venue's local clock, stored as if UTC; a match within
    # hours of midnight could sit a day off. Upgrade with a venue timezone if that ever matters.
    start = f"{m['match_date']}T{(m.get('kick_off') or '00:00:00')[:8]}"
    fixture = {
        "sport": "football",
        "mid": mid,
        "competition": m["competition"]["competition_name"],
        "season": m["season"]["season_name"],
        "start": start,
        "home": home,
        "away": away,
        "hg": m["home_score"],
        "ag": m["away_score"],
    }
    apps, by_id = [], {}
    for t in lineups:
        for p in t.get("lineup") or []:
            minutes = sum(
                (_clock(pos["to"]) if pos.get("to") else end) - _clock(pos["from"])
                for pos in p.get("positions") or []
            )
            if minutes <= 0:
                continue
            name = nick.get(p["player_id"], feed._s(p["player_name"]))
            by_id[p["player_id"]] = {
                "sport": "football",
                "mid": mid,
                "player": name,
                "identity": str(p["player_id"]),
                "team": feed._side(t["team_name"]),
                "start": start,
                "competition": fixture["competition"],
                "season": fixture["season"],
                "minutes": minutes,
                "totals": {"goals": 0, "shots": 0, "xg": 0.0, "assists": 0},
            }
            apps.append(by_id[p["player_id"]])
    for ev in events:
        row = by_id.get((ev.get("player") or {}).get("id"))
        kind = feed._name(ev.get("type"))
        if row is None or ev.get("period") == 5:  # shootout kicks are not chances
            continue
        if kind == "Shot":
            shot = ev.get("shot") or {}
            row["totals"]["shots"] += 1
            row["totals"]["goals"] += feed._name(shot.get("outcome")) == "Goal"
            row["totals"]["xg"] = round(row["totals"]["xg"] + (shot.get("statsbomb_xg") or 0), 3)
        elif kind == "Pass" and (ev.get("pass") or {}).get("goal_assist"):
            row["totals"]["assists"] += 1
    return fixture, apps


def football() -> tuple[list[dict], list[dict]]:
    seen = {v for (sport, _), v in MATCHES.items() if sport == "football"}
    todo = [m for comp, season in sorted(seen) for m in feed.statsbomb_matches(comp, season)]
    print(f"football: {len(todo)} matches in {len(seen)} competition-seasons", flush=True)
    with ThreadPoolExecutor(12) as pool:
        got = [g for g in pool.map(_or_skip(football_match), todo) if g is not None]
    if skipped := len(todo) - len(got):
        print(f"football: skipped {skipped} malformed matches", flush=True)
    return [f for f, _ in got], [a for _, apps in got for a in apps]


def _or_skip(build):
    """`build`, with a malformed upstream record (a missing field, a wrong type) answered None so
    one bad match is skipped and counted. A network error still raises: a gap is never silent."""

    def run(*args):
        try:
            return build(*args)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            return None

    return run


# --- basketball: stats.nba.com play-by-play for the score and totals, the shot archive for the date


def _archive(name: str):
    """The CSV rows of one season archive of shufinskiy/nba_data, streamed from the download."""
    r = httpx.get(
        feed.NBA_PBP.format(name=name), timeout=httpx.Timeout(300.0), follow_redirects=True
    )
    r.raise_for_status()
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:xz") as tar:
        yield from csv.DictReader(io.TextIOWrapper(feed._csv(tar, name), encoding="utf-8"))


def basketball_season(year: int) -> tuple[list[dict], list[dict]]:
    """Regular season and playoffs of the NBA season starting `year`, one fixture per game."""
    season = f"{year}-{str(year + 1)[2:]}"
    meta = {}  # game id -> (date, home abbreviation, away abbreviation)
    skipped = 0
    for po in ("", "po_"):
        for r in _archive(f"shotdetail_{po}{year}"):
            if (got := _or_skip(_shot_meta)(r)) is None:
                skipped += 1
            else:
                meta[r["GAME_ID"]] = got
    games: dict[str, dict] = {}
    for po in ("", "po_"):
        for r in _archive(f"nbastats_{po}{year}"):
            gid = r["GAME_ID"]
            if gid not in meta:
                continue
            g = games.setdefault(gid, {"names": {}, "totals": {}, "score": None})
            if _or_skip(_basketball_row)(g, r, meta[gid]) is None:
                skipped += 1
    if skipped:
        print(f"basketball {season}: skipped {skipped} malformed rows", flush=True)
    fixtures, apps = [], []
    for gid, g in games.items():
        date, home, away = meta[gid]
        if not g["score"] or home not in g["names"] or away not in g["names"]:
            continue
        mid, start = (
            gid.zfill(10),
            f"{date}T23:59:59",
        )  # no kickoff in the archive: the whole day is "not before"
        fixtures.append(
            {
                "sport": "basketball",
                "mid": mid,
                "competition": "NBA",
                "season": season,
                "start": start,
                "home": g["names"][home],
                "away": g["names"][away],
                "hg": g["score"][1],
                "ag": g["score"][0],
            }
        )
        for (identity, name, abbr), totals in g["totals"].items():
            apps.append(
                {
                    "sport": "basketball",
                    "mid": mid,
                    "player": name,
                    "identity": identity,
                    "team": g["names"][abbr],
                    "start": start,
                    "competition": "NBA",
                    "season": season,
                    "minutes": 0,  # the play-by-play has no minutes
                    "totals": totals,
                }
            )
    return fixtures, apps


def _shot_meta(r: dict) -> tuple:
    d = r["GAME_DATE"]
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}", r["HTM"], r["VTM"]


def _basketball_row(g: dict, r: dict, meta: tuple) -> bool:
    _, home, away = meta
    text = r["HOMEDESCRIPTION"] + r["VISITORDESCRIPTION"]
    if r["SCORE"]:
        away_pts, home_pts = (int(x) for x in r["SCORE"].split(" - "))
        g["score"] = (away_pts, home_pts)
    kind, who = r["EVENTMSGTYPE"], {}
    for n in (1, 2, 3):
        abbr, name = r[f"PLAYER{n}_TEAM_ABBREVIATION"], feed._s(r[f"PLAYER{n}_NAME"])
        if name and abbr in (home, away):
            g["names"][abbr] = feed._team(r, n)
            identity = feed._s(r.get(f"PLAYER{n}_ID")) or f"team:{abbr}:{name}"
            who[n] = g["totals"].setdefault(
                (identity, name, abbr), {"points": 0, "rebounds": 0, "assists": 0}
            )
    if 1 in who:
        if kind == "1":
            who[1]["points"] += 3 if "3PT" in text else 2
            if 2 in who and "AST" in text:
                who[2]["assists"] += 1
        elif kind == "3" and "MISS" not in text:
            who[1]["points"] += 1
        elif kind == "4":
            who[1]["rebounds"] += 1
    return True


def basketball() -> tuple[list[dict], list[dict]]:
    years = sorted(
        {int(a[-4:]) for (sport, _), arch in MATCHES.items() if sport == "basketball" for a in arch}
    )
    print(f"basketball: seasons {years}", flush=True)
    got = [basketball_season(y) for y in years]
    return [f for fs, _ in got for f in fs], [a for _, aps in got for a in aps]


# --- cricket: Cricsheet T20Is of the sample matches' years


def cricket_match(m: dict) -> tuple[dict, list[dict]]:
    info = m["info"]
    teams = [feed._s(t) for t in info["teams"]]
    day = info["dates"][0]
    start = f"{day}T23:59:59"  # no start time in Cricsheet: the whole day is "not before"
    score = dict.fromkeys(teams, 0)
    people = (info.get("registry") or {}).get("people") or {}
    tot, by_team_name, played = {}, {}, set()  # played: who batted or bowled a ball
    for team, names in info["players"].items():
        for name in names:
            team = feed._s(team)
            identity = feed._s(people.get(name)) or f"team:{team}:{name}"
            by_team_name[(team, name)] = identity
            tot[identity] = {
                "player": feed._s(name),
                "team": feed._s(team),
                "identity": identity,
                "totals": {"runs": 0, "balls": 0, "wickets": 0},
            }
    for inn in m.get("innings") or []:
        if inn.get("super_over"):
            continue
        for over in inn.get("overs") or []:
            for d in over.get("deliveries") or []:
                score[feed._s(inn["team"])] = (
                    score.get(feed._s(inn["team"]), 0) + d["runs"]["total"]
                )
                batting_team = feed._s(inn["team"])
                bowling_team = next((t for t in teams if t != batting_team), "")
                batter = tot.get(by_team_name.get((batting_team, d["batter"])))
                bowler = tot.get(by_team_name.get((bowling_team, d["bowler"])))
                played |= {p["identity"] for p in (batter, bowler) if p}
                bat = batter
                if bat and "wides" not in d.get("extras", {}):
                    bat["totals"]["balls"] += 1
                if bat:
                    bat["totals"]["runs"] += d["runs"]["batter"]
                for w in d.get("wickets") or []:
                    if bowler and w["kind"] not in NOT_BOWLERS:
                        bowler["totals"]["wickets"] += 1
    fixture = {
        "sport": "cricket",
        "mid": "",
        "gender": info.get("gender"),  # Cricsheet mixes men's and women's under one team name
        "competition": "T20I",  # one stretch per year: a tour's few games would be no season
        "season": day[:4],
        "start": start,
        "home": teams[0],
        "away": teams[1],
        "hg": score[teams[0]],
        "ag": score[teams[1]],
    }
    apps = [
        {
            **{k: fixture[k] for k in ("sport", "competition", "season", "start", "gender")},
            "mid": "",
            "player": t["player"],
            "identity": t["identity"],
            "team": t["team"],
            "minutes": 0,
            "totals": t["totals"],
        }
        for identity, t in tot.items()
        if identity in played
    ]
    return fixture, apps


def cricket() -> tuple[list[dict], list[dict]]:
    years = {a for (sport, _), arch in MATCHES.items() if sport == "cricket" for a in arch}
    print(f"cricket: years {sorted(years)}", flush=True)
    archive = feed.cricsheet_zip()
    fixtures, apps, skipped = [], [], 0
    for n in sorted(archive.namelist()):
        if not n.endswith(".json"):
            continue
        got = _or_skip(_cricket_file)(archive, n, years)
        if got is None:
            skipped += 1
        if not got:
            continue
        f, a = got
        mid = n.removesuffix(".json")
        f["mid"] = mid
        for row in a:
            row["mid"] = mid
        fixtures.append(f)
        apps += a
    if skipped:
        print(f"cricket: skipped {skipped} malformed matches", flush=True)
    return fixtures, apps


def _cricket_file(archive, n: str, years: set) -> tuple | bool:
    """One Cricsheet file as (fixture, appearances), or False when it is outside the years."""
    m = json.loads(archive.read(n))
    if not m["info"].get("dates") or m["info"]["dates"][0][:4] not in years:
        return False
    return cricket_match(m)


BUILDERS = {"football": football, "basketball": basketball, "cricket": cricket}


def stints(apps: list[dict]) -> list[dict]:
    """One record per player, team and season, its games as rows [start, minutes, *totals]: a
    record per appearance repeated every field name and made the store four times the size."""
    out: dict[tuple, dict] = {}
    for a in sorted(apps, key=lambda a: a["start"]):
        identity = a.get("identity") or f"team:{a['team']}:{a['player']}"
        key = (
            a["sport"],
            identity,
            a["player"],
            a["team"],
            a["competition"],
            a["season"],
            a.get("gender"),
        )
        rec = out.setdefault(
            key,
            {
                "id": list(key),
                **dict(
                    zip(
                        ("sport", "identity", "player", "team", "competition", "season", "gender"),
                        key,
                        strict=True,
                    )
                ),
                "keys": list(a["totals"]),
                "games": [],
            },  # fmt: skip
        )
        rec["games"].append([a["start"], a["minutes"], *a["totals"].values()])
    return list(out.values())


def write(sport_rows: dict[str, tuple[list[dict], list[dict]]], path: Path = GRAPH) -> None:
    """Replace the store at `path` with these fixtures and appearances."""
    from surrealdb import Surreal

    shutil.rmtree(path, ignore_errors=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = Surreal(f"surrealkv://{path}")
    db.connect()
    db.use("touchline", "follow")
    db.query(
        "DEFINE INDEX fx_home ON fixture FIELDS sport, home; "
        "DEFINE INDEX fx_away ON fixture FIELDS sport, away; "
        "DEFINE INDEX ap_team ON appearance FIELDS sport, team; "
        "DEFINE INDEX ap_player ON appearance FIELDS sport, player"
    )
    for fixtures, apps in sport_rows.values():
        fixtures = [{"id": [f["sport"], f["mid"]], **f} for f in fixtures]
        apps = stints(apps)
        for table, rows in (("fixture", fixtures), ("appearance", apps)):
            for i in range(0, len(rows), 2000):
                db.query(f"INSERT INTO {table} $rows RETURN NONE", {"rows": rows[i : i + 2000]})


def main(argv: list[str]) -> None:
    sports = argv or list(BUILDERS)
    write({s: BUILDERS[s]() for s in sports})
    print(f"wrote {GRAPH}")


if __name__ == "__main__":
    main(sys.argv[1:])
