"""Build data/graph: every team and player of each sample match's competition and season, on disk.

    uv run python scripts/build_graph.py [football]

Offline, like agent/packs.py: it reuses agent/feed.py's names and URLs, streams every match of the
competition-season (nothing is cached, raw events are dropped after each match) and writes
SurrealDB's embedded surrealkv store to data/graph, shipped in the image. Two tables:

    fixture     one per match: sport, competition, season, start (ISO kickoff), home, away, score
    appearance  one per player per match: team, start, minutes, sport-specific totals
"""

import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from agent import feed
from agent.packs import MATCHES

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
        got = list(pool.map(football_match, todo))
    return [f for f, _ in got], [a for _, apps in got for a in apps]


BUILDERS = {"football": football}


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
        apps = [{"id": [a["sport"], a["mid"], a["player"], a["team"]], **a} for a in apps]
        for table, rows in (("fixture", fixtures), ("appearance", apps)):
            for i in range(0, len(rows), 2000):
                db.query(f"INSERT INTO {table} $rows RETURN NONE", {"rows": rows[i : i + 2000]})


def main(argv: list[str]) -> None:
    sports = argv or list(BUILDERS)
    write({s: BUILDERS[s]() for s in sports})
    print(f"wrote {GRAPH}")


if __name__ == "__main__":
    main(sys.argv[1:])
