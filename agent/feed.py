"""Match feeds to Moments: StatsBomb open data (football) and Cricsheet (cricket).

Downloads are untrusted: every field that reaches a Moment is coerced to a short string or a
number, and the match header never carries the result. The picker follows the day spec (R11).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
STATSBOMB = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
CRICSHEET_ZIP = "https://cricsheet.org/downloads/t20s_json.zip"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

DEMO = {("football", "3906390"), ("cricket", "1298150")}  # WWC 2023 final; Ind v Pak 2022


def held_out(sport: str, match_id: str) -> bool:
    return int(hashlib.sha256(f"{sport}:{match_id}".encode()).hexdigest(), 16) % 5 == 0


def _s(value, limit: int = 60) -> str:
    return " ".join(str(value or "").split())[:limit]


def _num(value) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _fetch(url: str, name: str, timeout=TIMEOUT) -> bytes:
    path = CACHE / name
    if not path.exists():
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    return path.read_bytes()


def _name(obj) -> str:
    return _s(obj.get("name")) if isinstance(obj, dict) else ""


# --- football -----------------------------------------------------------------------------

def statsbomb_matches(comp: int, season: int) -> list[dict]:
    return json.loads(_fetch(f"{STATSBOMB}/matches/{comp}/{season}.json", f"sb_m_{comp}_{season}.json"))


def statsbomb_events(match_id: str) -> list[dict]:
    return json.loads(_fetch(f"{STATSBOMB}/events/{match_id}.json", f"sb_e_{match_id}.json"))


def football_header(meta: dict) -> dict:
    """Teams, competition and date only: never the score or result."""
    return {
        "sport": "football",
        "match_id": _s(meta.get("match_id")),
        "home": _s(meta.get("home_team", {}).get("home_team_name")),
        "away": _s(meta.get("away_team", {}).get("away_team_name")),
        "competition": _s(meta.get("competition", {}).get("competition_name")),
        "stage": _s(meta.get("competition_stage", {}).get("name")),
        "date": _s(meta.get("match_date"), 10),
    }


def football_moments(header: dict, events: list[dict]) -> list[dict]:
    home = header["home"]
    score = {"home": 0, "away": 0}
    shootout = {"home": 0, "away": 0}
    keepers = {}  # event id of a saved shot -> keeper name, from Goal Keeper events
    for ev in events:
        gk = ev.get("goalkeeper") or {}
        if _name(ev.get("type")) == "Goal Keeper" and "Saved" in _name(gk.get("type")):
            for rel in ev.get("related_events") or []:
                keepers[rel] = _name(ev.get("player"))

    moments = []
    for ev in events:
        kind = _name(ev.get("type"))
        team = _name(ev.get("team"))
        player = _name(ev.get("player"))
        period = _num(ev.get("period")) or 0
        side = "home" if team == home else "away"
        other = "away" if side == "home" else "home"
        players, detail, outcome = {}, {}, ""
        if kind == "Shot":
            shot = ev.get("shot") or {}
            outcome = _name(shot.get("outcome"))
            players["shooter"] = player
            if ev.get("id") in keepers:
                players["keeper"] = keepers[ev["id"]]
            detail = {
                "shot_type": _name(shot.get("type")),
                "body_part": _name(shot.get("body_part")),
                "technique": _name(shot.get("technique")),
                "xg": round(_num(shot.get("statsbomb_xg")) or 0.0, 2),
            }
            if outcome == "Goal":
                (shootout if period == 5 else score)[side] += 1
        elif kind == "Own Goal Against":
            outcome = "Own goal"
            players["scorer"] = player
            score[other] += 1
        elif kind in ("Foul Committed", "Bad Behaviour"):
            card = _name((ev.get("foul_committed") or ev.get("bad_behaviour") or {}).get("card"))
            if not card:
                continue
            outcome = card
            players["offender"] = player
            detail = {"card": card}
        elif kind == "Substitution":
            sub = ev.get("substitution") or {}
            outcome = _name(sub.get("outcome")) or "Substitution"
            players = {"off": player, "on": _name(sub.get("replacement"))}
        elif kind == "Injury Stoppage":
            outcome = "Injury stoppage"
            players["injured"] = player
        else:
            continue
        if period == 5:
            detail["shootout"] = dict(shootout)
        loc = ev.get("location") if isinstance(ev.get("location"), list) else []
        moment = {
            "sport": "football",
            "match_id": header["match_id"],
            "idx": len(moments),
            "period": period,
            "clock": f"{_num(ev.get('minute')) or 0:02d}:{_num(ev.get('second')) or 0:02d}",
            "type": kind,
            "team": team,
            "players": {k: v for k, v in players.items() if v},
            "outcome": outcome,
            "score": dict(score),
            "detail": detail,
        }
        if len(loc) >= 2 and _num(loc[0]) is not None and _num(loc[1]) is not None:
            moment["x"], moment["y"] = loc[0], loc[1]
        moments.append(moment)
    return moments


# --- cricket ------------------------------------------------------------------------------

def cricsheet_zip() -> zipfile.ZipFile:
    data = _fetch(CRICSHEET_ZIP, "t20s_json.zip", timeout=httpx.Timeout(120.0, connect=10.0))
    return zipfile.ZipFile(io.BytesIO(data))


def cricsheet_match(match_id: str, archive: zipfile.ZipFile | None = None) -> dict:
    return json.loads((archive or cricsheet_zip()).read(f"{match_id}.json"))


def cricket_header(match_id: str, match: dict) -> dict:
    """Teams, event and date only: never the outcome or player of the match."""
    info = match.get("info") or {}
    teams = [_s(t) for t in info.get("teams") or []] + ["", ""]
    event = info.get("event") if isinstance(info.get("event"), dict) else {}
    return {
        "sport": "cricket",
        "match_id": _s(match_id),
        "home": teams[0],
        "away": teams[1],
        "competition": _s(event.get("name")),
        "stage": _s(event.get("stage"))
        or (f"match {_s(event.get('match_number'))}" if event.get("match_number") else ""),
        "date": _s((info.get("dates") or [""])[0], 10),
    }


def _runs(total) -> str:
    n = _num(total) or 0
    return "dot ball" if n == 0 else f"{n} run" if n == 1 else f"{n} runs"


def cricket_moments(header: dict, match: dict) -> list[dict]:
    info = match.get("info") or {}
    max_overs = _num(info.get("overs")) or 20
    moments = []
    for inn_no, inn in enumerate(match.get("innings") or [], start=1):
        if inn.get("super_over"):
            continue
        team = _s(inn.get("team"))
        target = _num((inn.get("target") or {}).get("runs"))
        runs = wickets = legal = 0
        free_hit = False
        balls = [(o, d) for o in inn.get("overs") or [] for d in o.get("deliveries") or []]
        for n, (over, d) in enumerate(balls):
            over_no = _num(over.get("over")) or 0
            r = d.get("runs") or {}
            extras = d.get("extras") or {}
            batter_runs = _num(r.get("batter")) or 0
            before = runs
            runs += _num(r.get("total")) or 0
            outs = [w for w in d.get("wickets") or [] if isinstance(w, dict)]
            wickets += len(outs)
            legal += not (extras.get("wides") or extras.get("noballs"))
            last_ball = n == len(balls) - 1
            tight_chase = (
                target is not None and over_no >= max_overs - 2 and target - before <= 30
            )
            if outs:
                kind, outcome = "Wicket", _s(outs[0].get("kind"))
            elif batter_runs in (4, 6):
                kind, outcome = ("Six" if batter_runs == 6 else "Four"), f"{batter_runs} runs"
            elif extras.get("noballs"):
                kind, outcome = "No ball", _runs(r.get("total"))
            elif last_ball or tight_chase:
                kind = "Last ball" if last_ball else "Chase"
                outcome = "wide" if extras.get("wides") else _runs(r.get("total"))
            else:
                kind = None
            if kind:
                players = {
                    "batter": _s(d.get("batter")),
                    "bowler": _s(d.get("bowler")),
                    "non_striker": _s(d.get("non_striker")),
                }
                if outs:
                    players["out"] = _s(outs[0].get("player_out"))
                    fielders = outs[0].get("fielders") or []
                    if fielders and isinstance(fielders[0], dict):
                        players["fielder"] = _name(fielders[0])
                detail = {
                    "runs_batter": batter_runs,
                    "extras": {k: v for k, v in extras.items() if _num(v) is not None},
                    "free_hit": free_hit,
                }
                if outs:
                    detail["wicket_kind"] = _s(outs[0].get("kind"))
                if target is not None:
                    detail["balls_left"] = max(0, max_overs * 6 - legal)
                score = {"runs": runs, "wickets": wickets}
                if target is not None:
                    score["target"] = target
                moments.append({
                    "sport": "cricket",
                    "match_id": header["match_id"],
                    "idx": len(moments),
                    "period": inn_no,
                    "clock": _s(d.get("actual_delivery"), 8) or f"{over_no}.{n}",
                    "type": kind,
                    "team": team,
                    "players": {k: v for k, v in players.items() if v},
                    "outcome": outcome,
                    "score": score,
                    "detail": detail,
                })
            # A free hit follows a no-ball and lasts until the next legal delivery.
            if extras.get("noballs"):
                free_hit = True
            elif not extras.get("wides"):
                free_hit = False
    return moments


def load(sport: str, match_id: str, meta: dict | None = None) -> tuple[dict, list[dict]]:
    """(header, moments) for one match. Football needs its StatsBomb match record as meta."""
    if sport == "football":
        header = football_header(meta or {"match_id": match_id})
        return header, football_moments(header, statsbomb_events(match_id))
    match = cricsheet_match(match_id)
    header = cricket_header(match_id, match)
    return header, cricket_moments(header, match)
