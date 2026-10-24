"""Players, teams, matches and seasons as a graph (#300), behind Follow a player.

SurrealDB's embedded engine runs in this process, in memory: no service, secret or setting on Cloud
Run. `start()` loads it once from data/packs and data/sample, with fixed record ids in file order,
so every load is the same. `pack()` reads a match's pack back from the graph in the JSON pack's
shape, so `predict` cuts it at the moment on screen exactly as before. Any engine or query error
logs its type and returns None, and the caller uses the JSON pack: the page never breaks on it.

    player -plays_for-> team          player -played_in-> match <-competed- team
    match.season -> season            played_in: team, pre-match record, tonight's totals
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from core.predict import PACKS

log = logging.getLogger("touchline.graph")
SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"
STORE = Path(__file__).resolve().parent.parent / "data" / "graph"  # scripts/build_graph.py

_db = None  # the connection once loaded; None means the JSON path
_kv = None  # the on-disk store of every team and player of each sample competition
_lock = threading.Lock()  # one query at a time on the one embedded connection


def _season(sport: str, competition: str, window: dict) -> dict:
    """The stretch of a competition a match's pre-match record covers: "NBA 2005-06"."""
    start, end = window["from"][:4], window["to"][:4]
    label = start if start == end else f"{start}-{end[2:]}"
    return {"sport": sport, "competition": competition, "label": label, **window}


def _totals(sport: str, name: str, tonight: list[dict]) -> dict:
    """A player's whole-match totals for the edge. Never served for the match on screen."""
    if sport == "cricket":
        bat = [t for t in tonight if t["batter"] == name]
        wickets = sum(bool(t["out"]) for t in tonight if t["bowler"] == name)
        return {"balls": len(bat), "runs": sum(t["runs"] for t in bat), "wickets": wickets}
    mine = [t for t in tonight if t.get("player") == name]
    out = {"attempts": len(mine), "made": sum(bool(t["made"]) for t in mine)}
    if sport == "football":
        out["xg"] = round(sum(t["xg"] for t in mine), 2)
    return out


def _before(record: dict) -> dict:
    """A pack's player record as the edge keeps it. SurrealDB sorts an object's keys, and the order
    of `zones` breaks ties in the profile, so zones go in as [zone, counts] pairs."""
    # shortcut: no season shots, as the shot map still reads the pack; add them to move it here
    out = {k: v for k, v in record.items() if k != "shots"}
    if "zones" in out:
        out["zones"] = [[z, c] for z, c in out["zones"].items()]
    return out


def rows(packs: Path = PACKS, sample: Path = SAMPLE) -> dict[str, list[dict]]:
    """Every record and edge to insert, by table, in file order: plain data, no engine needed."""
    from surrealdb import RecordID as R

    out: dict[str, list[dict]] = {
        t: [] for t in ("season", "match", "team", "player", "plays_for", "played_in", "competed")
    }
    seen: set = set()

    def once(table: str, row: dict) -> None:
        if (table, str(row["id"])) not in seen:
            seen.add((table, str(row["id"])))
            out[table].append(row)

    for path in sorted(sample.glob("*.json")):
        if not (packs / path.name).exists():  # a match with no pack has nobody to follow
            continue
        h = json.loads(path.read_text(encoding="utf-8"))["header"]
        sport, mid = h["sport"], h["match_id"]
        pack = json.loads((packs / path.name).read_text(encoding="utf-8"))
        season = _season(sport, h["competition"], pack["window"])
        season_id = R("season", [sport, h["competition"], season["label"]])
        once("season", {"id": season_id, **season})
        sides = f"{h['home']} v {h['away']}, " if "home" in h else ""  # as data.matches titles it
        match = R("match", mid)
        once(
            "match",
            {
                "id": match,
                "match_id": mid,
                "title": f"{sides}{h['competition']} {h['stage']}".strip(),
                "date": h["date"],
                "season": season_id,
                **{k: v for k, v in pack.items() if k not in ("match_id", "players", "teams")},
            },
        )
        for order, (team, totals) in enumerate(pack["teams"].items()):
            team_id = R("team", [sport, team])
            once("team", {"id": team_id, "sport": sport, "name": team})
            edge = {"id": R("competed", [mid, team]), "in": team_id, "out": match}
            once("competed", {**edge, "order": order, "totals": totals})
        for order, (name, record) in enumerate(pack["players"].items()):
            player, team_id = R("player", [sport, name]), R("team", [sport, record["team"]])
            once("player", {"id": player, "sport": sport, "name": name})
            once("team", {"id": team_id, "sport": sport, "name": record["team"]})
            edge = {"id": R("plays_for", [sport, name, record["team"]]), "in": player}
            once("plays_for", {**edge, "out": team_id})
            once(
                "played_in",
                {
                    "id": R("played_in", [mid, name]),
                    "in": player,
                    "out": match,
                    "team": record["team"],
                    "order": order,
                    "before": _before(record),
                    "totals": _totals(sport, name, pack["tonight"]),
                },
            )
    return out


def load(packs: Path = PACKS, sample: Path = SAMPLE):
    """A fresh in-memory graph of every bundled match."""
    from surrealdb import Surreal

    db = Surreal("mem://")
    db.connect()
    db.use("touchline", "follow")
    for table, batch in rows(packs, sample).items():
        relation = "RELATION " if table in ("plays_for", "played_in", "competed") else ""
        db.query(f"INSERT {relation}INTO {table} $rows RETURN NONE", {"rows": batch})
    return db


def start() -> float | None:
    """Load the graph once per process; the seconds it took, or None when it is off."""
    global _db
    with _lock:
        if _db is not None:
            return 0.0
        t = time.perf_counter()
        try:
            _db = load()
        except Exception as exc:  # no engine, no wheel, bad data: Follow a player reads the JSON
            log.warning("graph off, Follow a player reads the packs: %s", type(exc).__name__)
            return None
        _open_store()
        took = time.perf_counter() - t
        log.info("graph loaded in %.2f s", took)
        return took


def _query(sql: str, params: dict):
    if _db is None:
        return None
    try:
        with _lock:
            return _db.query(sql, params)
    except Exception as exc:
        log.warning("graph query failed, reading the pack: %s", type(exc).__name__)
        return None


PACK = """SELECT *,
  (SELECT in.name AS name, before, order FROM $m<-played_in ORDER BY order) AS roster,
  (SELECT in.name AS name, totals, order FROM $m<-competed ORDER BY order) AS sides
FROM ONLY $m"""


def pack(match_id: str) -> dict | None:
    """What Follow a player reads of the match's pack, from the graph, in the pack's shape; None
    when the graph is off or lacks the match."""
    if _db is None:
        return None
    from surrealdb import RecordID

    m = _query(PACK, {"m": RecordID("match", str(match_id))})
    if not m:
        return None
    players = {p["name"]: p["before"] for p in m["roster"]}
    for p in players.values():
        if "zones" in p:
            p["zones"] = dict(p["zones"])
        if "bowling" in p:  # the SDK writes None as NONE, which drops the key: put it back
            p["bowling"].setdefault("economy", None)
    return {
        "match_id": m["match_id"],
        "sport": m["sport"],
        "window": m["window"],
        "players": players,
        "teams": {t["name"]: t["totals"] for t in m["sides"]},
        "tonight": m["tonight"],
    }


LIBRARY = """SELECT out.match_id AS match_id, out.title AS title, out.date AS date, team,
  array::sort((SELECT VALUE in.name FROM $parent.out<-played_in
    WHERE team = $parent.team AND in != $p)) AS teammates
FROM $p->played_in WHERE out != $m ORDER BY date"""


def library(sport: str, match_id: str, name: str) -> list[dict]:
    """Also in our library: the player's other matches, each with their teammates there. Never the
    match on screen, so nothing from it, later moments included, can show."""
    if _db is None:
        return []
    from surrealdb import RecordID

    found = _query(
        LIBRARY,
        {"p": RecordID("player", [sport, name]), "m": RecordID("match", str(match_id))},
    )
    return found or []


# --- the competition store: data/graph on disk, read by the contract functions below -------------


def _open_store(path: Path = STORE) -> None:
    """Open data/graph. surrealkv writes to its directory even to read, and the image's is not
    writable by the app user, so it opens a copy under tmp; a failure leaves the contract off."""
    global _kv
    try:
        from surrealdb import Surreal

        work = Path(tempfile.mkdtemp(prefix="graph-")) / "db"
        shutil.copytree(path, work)
        _kv = Surreal(f"surrealkv://{work}")
        _kv.connect()
        _kv.use("touchline", "follow")
    except Exception as exc:
        _kv = None
        log.warning("competition graph off, callers read the packs: %s", type(exc).__name__)


def _rows(sql: str, params: dict) -> list[dict] | None:
    if _kv is None:
        return None
    try:
        with _lock:
            return _kv.query(sql, params)
    except Exception as exc:
        log.warning("graph query failed, reading the packs: %s", type(exc).__name__)
        return None


def _utc(before: str) -> str | None:
    """`before` as a UTC wall clock in the store's own form. Stored starts are UTC; a time with an
    offset is converted, a bare time or date is taken as UTC (a date alone is that day's midnight,
    so nothing on the day is "before"). Unreadable: None, and the caller answers empty."""
    try:
        t = datetime.fromisoformat(before)
    except (TypeError, ValueError):
        log.warning("graph cut-off unreadable, reading the packs")
        return None
    t = t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S")


def _result(f: dict, team: str) -> dict:
    home = f["home"] == team
    mine, theirs = (f["hg"], f["ag"]) if home else (f["ag"], f["hg"])
    return {
        "date": f["start"][:10],
        "opponent": f["away"] if home else f["home"],
        "home": home,
        "score": f"{mine}-{theirs}",
        "result": "W" if mine > theirs else "L" if mine < theirs else "D",
    }


FIXTURES = """SELECT * FROM fixture WHERE sport = $s AND start < $b
  AND (home = $t OR away = $t) {more} ORDER BY start DESC LIMIT $n"""


def team_form(sport: str, team: str, before: str, n: int = 5) -> list[dict]:
    """The team's last `n` matches before `before`, newest first, score as the team's own."""
    if (cut := _utc(before)) is None:
        return []
    found = _rows(FIXTURES.format(more=""), {"s": sport, "t": team, "b": cut, "n": n})
    return [_result(f, team) for f in found or []]


def head_to_head(sport: str, a: str, b: str, before: str, n: int = 5) -> list[dict]:
    """The last `n` meetings of a and b before `before`, newest first, seen from a."""
    if (cut := _utc(before)) is None:
        return []
    sql = FIXTURES.format(more="AND (home = $o OR away = $o)")
    found = _rows(sql, {"s": sport, "t": a, "o": b, "b": cut, "n": n})
    return [_result(f, a) for f in found or []]


APPEARANCES = "SELECT * FROM appearance WHERE sport = $s AND {who} = $w"
LEAD = {"football": "goals", "basketball": "points", "cricket": "runs", "f1": "points"}


def _games(sport: str, who: str, w: str, before: str) -> list[dict] | None:
    """The player's (or team's) appearances before `before`, oldest first, one dict per game."""
    found = _rows(APPEARANCES.format(who=who), {"s": sport, "w": w})
    if found is None or (cut := _utc(before)) is None:
        return None
    return sorted(
        (
            {
                **{k: r[k] for k in ("player", "team", "competition", "season")},
                "start": g[0],
                "totals": dict(zip(r["keys"], g[2:], strict=True)),
            }  # fmt: skip
            for r in found
            for g in r["games"]
            if g[0] < cut
        ),
        key=lambda a: a["start"],
    )


def _sum(apps: list[dict]) -> dict:
    out: dict = {}
    for a in apps:
        for k, v in a["totals"].items():
            out[k] = round(out.get(k, 0) + v, 2)
    return out


def _latest(apps: list[dict]) -> list[dict]:
    """The appearances in the newest competition-season of the list (oldest first)."""
    last = apps[-1]
    return [
        a for a in apps if (a["competition"], a["season"]) == (last["competition"], last["season"])
    ]


def player_season(sport: str, name: str, before: str) -> dict | None:
    """The player's newest competition-season before `before`: team, matches and summed totals."""
    apps = _games(sport, "player", name, before)
    if not apps:
        return None
    mine = _latest(apps)
    return {
        "team": mine[-1]["team"],
        "competition": mine[-1]["competition"],
        "season": mine[-1]["season"],
        "matches": len(mine),
        "totals": _sum(mine),
    }


def squad(sport: str, team: str, before: str) -> list[dict]:
    """Who played for the team in its newest competition-season before `before`, best first."""
    apps = _games(sport, "team", team, before)
    if not apps:
        return []
    by: dict[str, list[dict]] = {}
    for a in _latest(apps):
        by.setdefault(a["player"], []).append(a)
    lead = LEAD.get(sport, "points")
    ranked = sorted(by.items(), key=lambda kv: (-_sum(kv[1]).get(lead, 0), -len(kv[1]), kv[0]))
    return [
        {"name": n, "matches": len(a), "headline": f"{_sum(a).get(lead, 0):g} {lead} in {len(a)}"}
        for n, a in ranked
    ]


def teams(sport: str) -> list[dict]:
    """Every team in the store with its competition, season and match count."""
    found = _rows("SELECT * FROM fixture WHERE sport = $s", {"s": sport})
    count: dict[tuple, int] = {}
    for f in found or []:
        for side in (f["home"], f["away"]):
            key = (side, f["competition"], f["season"])
            count[key] = count.get(key, 0) + 1
    return [
        {"team": t, "competition": c, "season": s, "matches": m}
        for (t, c, s), m in sorted(count.items())
    ]
