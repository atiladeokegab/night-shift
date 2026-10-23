"""Match feeds to Moments: StatsBomb open data (football) and Cricsheet (cricket).

Downloads are untrusted: every field that reaches a Moment is coerced to a short string or a
number, and the match header never carries the result. The picker follows the day spec (R11).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import httpx

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
STATSBOMB = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
CRICSHEET_ZIP = "https://cricsheet.org/downloads/t20s_json.zip"
# stats.nba.com play-by-play (playbyplayv2), one archive per season, from the Apache-2.0 mirror
# shufinskiy/nba_data: stats.nba.com itself times out from cloud IPs.
NBA_PBP = "https://github.com/shufinskiy/nba_data/raw/main/datasets/{name}.tar.xz"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# WWC 2023 final; Ind v Pak 2022; WC 2022 final
DEMO = {
    ("football", "3906390"),
    ("cricket", "1298150"),
    ("football", "3869685"),
    ("basketball", "0049700088"),  # Jordan, 1998 Finals Game 6
    ("basketball", "0020500591"),  # Kobe's 81 v Toronto
}


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
    return json.loads(
        _fetch(f"{STATSBOMB}/matches/{comp}/{season}.json", f"sb_m_{comp}_{season}.json")
    )


def statsbomb_events(match_id: str) -> list[dict]:
    return json.loads(_fetch(f"{STATSBOMB}/events/{match_id}.json", f"sb_e_{match_id}.json"))


# StatsBomb player id -> the name commentators use, where StatsBomb's own nickname is wrong.
NAME_OVERRIDES = {22097: "Kolo Muani"}  # StatsBomb's nickname is "Randal Kolo"


def statsbomb_nicknames(match_id: str) -> dict[int, str]:
    """Player id -> the name a commentator uses ("Lionel Messi"), from the match's lineups."""
    teams = json.loads(_fetch(f"{STATSBOMB}/lineups/{match_id}.json", f"sb_l_{match_id}.json"))
    return {
        p["player_id"]: _s(p["player_nickname"])
        for team in teams
        if isinstance(team, dict)
        for p in team.get("lineup") or []
        if isinstance(p, dict)
        if isinstance(p.get("player_id"), int) and _s(p.get("player_nickname"))
    } | NAME_OVERRIDES


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


def football_moments(
    header: dict, events: list[dict], nicknames: dict[int, str] | None = None
) -> list[dict]:
    nicknames = nicknames or {}

    def who(obj) -> str:  # the nickname when StatsBomb has one, else the full name
        return nicknames.get(obj.get("id"), _name(obj)) if isinstance(obj, dict) else ""

    home = header["home"]
    score = {"home": 0, "away": 0}
    shootout = {"home": 0, "away": 0}
    keepers = {}  # event id of a saved shot -> keeper name, from Goal Keeper events
    for ev in events:
        gk = ev.get("goalkeeper") or {}
        if _name(ev.get("type")) == "Goal Keeper" and "Saved" in _name(gk.get("type")):
            for rel in ev.get("related_events") or []:
                keepers[rel] = who(ev.get("player"))

    moments = []
    for ev in events:
        kind = _name(ev.get("type"))
        team = _name(ev.get("team"))
        player = who(ev.get("player"))
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
            players = {"off": player, "on": who(sub.get("replacement"))}
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
        runs = wickets = legal = in_over = 0
        this_over = None
        free_hit = False
        balls = [(o, d) for o in inn.get("overs") or [] for d in o.get("deliveries") or []]
        for n, (over, d) in enumerate(balls):
            over_no = _num(over.get("over")) or 0
            if over_no != this_over:
                this_over, in_over = over_no, 0
            # a wide or no-ball is re-bowled, so it carries the next legal ball's number
            ball_no = in_over + 1
            r = d.get("runs") or {}
            extras = d.get("extras") or {}
            batter_runs = _num(r.get("batter")) or 0
            before = runs
            runs += _num(r.get("total")) or 0
            outs = [w for w in d.get("wickets") or [] if isinstance(w, dict)]
            wickets += len(outs)
            is_legal = not (extras.get("wides") or extras.get("noballs"))
            legal += is_legal
            in_over += is_legal
            last_ball = n == len(balls) - 1
            tight_chase = target is not None and over_no >= max_overs - 2 and target - before <= 30
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
                moments.append(
                    {
                        "sport": "cricket",
                        "match_id": header["match_id"],
                        "idx": len(moments),
                        "period": inn_no,
                        "clock": _s(d.get("actual_delivery"), 8) or f"{over_no}.{ball_no}",
                        "type": kind,
                        "team": team,
                        "players": {k: v for k, v in players.items() if v},
                        "outcome": outcome,
                        "score": score,
                        "detail": detail,
                    }
                )
            # A free hit follows a no-ball and lasts until the next legal delivery.
            if extras.get("noballs"):
                free_hit = True
            elif not extras.get("wides"):
                free_hit = False
    return moments


# --- basketball ---------------------------------------------------------------------------

CLOSING = 120  # the last two minutes of the 4th quarter or overtime: every basket and steal
BIG_NIGHT = 40  # from 40 points, every field goal (and closing free throw) of that player


def nba_rows(game_id: str) -> list[dict]:
    """playbyplayv2 rows for one game; the season archive comes from the game id
    (00 + type + season: "0049700088" is the 1997-98 playoffs, "0020500591" 2005-06)."""
    if not (len(game_id) == 10 and game_id.isdigit() and game_id[2] in "24"):
        raise KeyError(game_id)
    yy = int(game_id[3:5])
    name = f"nbastats_{'po_' if game_id[2] == '4' else ''}{(1900 if yy >= 46 else 2000) + yy}"
    timeout = httpx.Timeout(120.0, connect=10.0)
    data = _fetch(NBA_PBP.format(name=name), f"{name}.tar.xz", timeout=timeout)
    want = str(int(game_id))  # the archive drops the leading zeros
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
        member = next(m for m in tar.getmembers() if m.isfile() and m.name.endswith(".csv"))
        text = io.TextIOWrapper(tar.extractfile(member), encoding="utf-8", newline="")
        rows = [r for r in csv.DictReader(text) if r.get("GAME_ID") == want]
    return sorted(rows, key=lambda r: (_int(r.get("PERIOD")), _int(r.get("EVENTNUM"))))


def _int(value) -> int:
    return int(value) if str(value or "").strip().isdigit() else 0


def _team(row: dict, n: int) -> str:
    return _s(
        f"{row.get(f'PLAYER{n}_TEAM_CITY') or ''} {row.get(f'PLAYER{n}_TEAM_NICKNAME') or ''}"
    )


def basketball_header(game_id: str, rows: list[dict], meta: dict | None = None) -> dict:
    """Teams from the feed; competition, stage and date from meta. Never the score or result."""
    meta = meta or {}
    home = next((_team(r, 1) for r in rows if r.get("HOMEDESCRIPTION") and _team(r, 1)), "")
    away = next((_team(r, 1) for r in rows if r.get("VISITORDESCRIPTION") and _team(r, 1)), "")
    return {
        "sport": "basketball",
        "match_id": _s(game_id),
        "home": home,
        "away": away,
        "competition": _s(meta.get("competition")),
        "stage": _s(meta.get("stage")),
        "date": _s(meta.get("date"), 10),
    }


def basketball_moments(header: dict, rows: list[dict]) -> list[dict]:
    score = {"home": 0, "away": 0}
    points: dict[str, int] = {}
    leader = None  # the side that last led, through ties
    last_period = max((_int(r.get("PERIOD")) for r in rows), default=0)
    moments = []
    for r in rows:
        kind_no, period = _int(r.get("EVENTMSGTYPE")), _int(r.get("PERIOD"))
        mm, _, ss = str(r.get("PCTIMESTRING") or "0:00").partition(":")
        left = _int(mm) * 60 + _int(ss)
        closing = period >= 4 and left <= CLOSING
        home_side = _team(r, 1) == header["home"]
        play = _s(r.get("HOMEDESCRIPTION") or r.get("VISITORDESCRIPTION"), 80)
        shooter = _s(r.get("PLAYER1_NAME"))
        players, detail, keep = {}, {}, False
        if kind_no == 1 or (kind_no == 3 and play and "MISS" not in play.upper()):
            made = 1 if kind_no == 3 else 3 if "3PT" in play.upper() else 2
            score["home" if home_side else "away"] += made
            after = score["home"] - score["away"]
            had = points.get(shooter, 0)
            points[shooter] = had + made
            kind = "Free throw" if kind_no == 3 else "Field goal"
            outcome = f"{made} point{'s' if made > 1 else ''}"
            team = _team(r, 1)
            players = {"shooter": shooter}
            if kind_no == 1 and _s(r.get("PLAYER2_NAME")):
                players["assist"] = _s(r.get("PLAYER2_NAME"))
            detail = {"play": play, "player_points": points[shooter]}
            if after == 0:
                detail["tied"] = True
            else:
                now = "home" if after > 0 else "away"
                if leader not in (None, now):
                    detail["lead_change"] = True
                leader = now
            milestone = points[shooter] // 10 > had // 10 and points[shooter] >= 30
            big = points[shooter] >= BIG_NIGHT and (kind_no == 1 or closing)
            keep = (
                (closing and kind_no == 1)
                or milestone
                or big
                or "tied" in detail
                or "lead_change" in detail
            )
        elif kind_no == 5 and closing and _s(r.get("PLAYER2_NAME")):
            # the steal is told on the stealer's side, the turnover on the other
            sides = (r.get("HOMEDESCRIPTION"), r.get("VISITORDESCRIPTION"))
            play = next((_s(d, 80) for d in sides if "STEAL" in str(d or "").upper()), "")
            kind, outcome, team, keep = "Steal", "Steal", _team(r, 2), bool(play)
            players = {"stealer": _s(r.get("PLAYER2_NAME")), "lost_by": shooter}
            detail = {"play": play}
        elif kind_no == 13 and period == last_period:
            kind, outcome, team, keep = "End of game", "Final buzzer", "", True
        if not keep:
            continue
        moments.append(
            {
                "sport": "basketball",
                "match_id": header["match_id"],
                "idx": len(moments),
                "period": period,
                "clock": f"{left // 60:02d}:{left % 60:02d}",
                "type": kind,
                "team": team,
                "players": {k: v for k, v in players.items() if v},
                "outcome": outcome,
                "score": dict(score),
                "detail": detail,
            }
        )
    return moments


def load(sport: str, match_id: str, meta: dict | None = None) -> tuple[dict, list[dict]]:
    """(header, moments) for one match. Football needs its StatsBomb match record as meta;
    basketball takes competition, stage and date from meta."""
    if sport == "football":
        header = football_header(meta or {"match_id": match_id})
        events, nicknames = statsbomb_events(match_id), statsbomb_nicknames(match_id)
        return header, football_moments(header, events, nicknames)
    if sport == "basketball":
        rows = nba_rows(match_id)
        header = basketball_header(match_id, rows, meta)
        return header, basketball_moments(header, rows)
    match = cricsheet_match(match_id)
    header = cricket_header(match_id, match)
    return header, cricket_moments(header, match)
