"""Match feeds to Moments: StatsBomb open data (football), Cricsheet (cricket), stats.nba.com
play-by-play (basketball) and OpenF1 (F1).

Downloads are untrusted: every field that reaches a Moment is coerced to a short string or a
number, and the match header never carries the result.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tarfile
import time
import zipfile
from datetime import datetime, timedelta
from itertools import groupby
from pathlib import Path

import httpx

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
STATSBOMB = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
CRICSHEET_ZIP = "https://cricsheet.org/downloads/t20s_json.zip"
# stats.nba.com play-by-play (playbyplayv2), one archive per season, from the Apache-2.0 mirror
# shufinskiy/nba_data: stats.nba.com itself times out from cloud IPs.
NBA_PBP = "https://github.com/shufinskiy/nba_data/raw/main/datasets/{name}.tar.xz"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# The seven demo matches; never replayed for training
DEMO = {
    ("football", "3754092"),
    ("cricket", "1298150"),
    ("football", "3869685"),
    ("football", "3913122"),  # Brighton v Bristol City, WSL 2024: the long tail
    ("football", "7457"),  # Orlando Pride 3-4 North Carolina Courage, NWSL 2018: a whole match
    ("cricket", "1515217"),  # Netherlands v Nepal, Women's T20 World Cup Qualifier 2026: whole
    ("basketball", "0049700088"),  # Jordan, 1998 Finals Game 6
    ("basketball", "0020500591"),  # Kobe's 81 v Toronto
    ("f1", "9636"),  # Verstappen, 2024 São Paulo Grand Prix
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
        for attempt in range(4):  # a dropped connection or a 5xx is retried, as build_graph does
            try:
                resp = httpx.get(url, timeout=timeout, follow_redirects=True)
                resp.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        CACHE.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")  # renamed only once whole: never a cut cache
        part.write_bytes(resp.content)
        part.replace(path)
    return path.read_bytes()


def _name(obj) -> str:
    return _s(obj.get("name")) if isinstance(obj, dict) else ""


def _side(name) -> str:
    return _s(name).removesuffix(" Women's")  # "Spain" in lines and the score bar


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
        "home": _side(meta.get("home_team", {}).get("home_team_name")),
        "away": _side(meta.get("away_team", {}).get("away_team_name")),
        "competition": _s(meta.get("competition", {}).get("competition_name")),
        "stage": _s(meta.get("competition_stage", {}).get("name")),
        "date": _s(meta.get("match_date"), 10),
    }


def football_moments(
    header: dict, events: list[dict], nicknames: dict[int, str] | None = None
) -> list[dict]:
    nicknames = nicknames or {}
    events = [ev for ev in events if isinstance(ev, dict)]  # a junk record is skipped, not fatal

    def who(obj) -> str:  # the nickname when StatsBomb has one, else the full name
        return nicknames.get(obj.get("id"), _name(obj)) if isinstance(obj, dict) else ""

    home = header["home"]
    knockout = _s(header.get("stage")) not in ("", "Group Stage", "Regular Season")
    score = {"home": 0, "away": 0}
    shootout = {"home": 0, "away": 0}
    keepers = {}  # event id of a saved shot -> keeper name, from Goal Keeper events
    for ev in events:
        gk = ev.get("goalkeeper") or {}
        if _name(ev.get("type")) == "Goal Keeper" and "Saved" in _name(gk.get("type")):
            for rel in ev.get("related_events") or []:
                keepers[rel] = who(ev.get("player"))

    moments, ats = [], []
    for ev in events:
        kind = _name(ev.get("type"))
        team = _side(_name(ev.get("team")))
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
        elif kind == "Half End" and period in (2, 4, 5):
            # the final whistle, from the score at the whistle (A-1.4): a level knockout goes on
            level = score["home"] == score["away"]
            if period < 5 and level and (period == 4 or knockout):
                continue
            kind = outcome = "Full time"
            team = ""
        else:
            continue
        if period == 5:
            detail["shootout"] = dict(shootout)
        loc = ev.get("location") if isinstance(ev.get("location"), list) else []
        mm, ss = (int(_num(ev.get(k)) or 0) for k in ("minute", "second"))  # 10.0 is 10, no crash
        moment = {
            "sport": "football",
            "match_id": header["match_id"],
            "idx": len(moments),
            "period": period,
            "clock": f"{mm:02d}:{ss:02d}",
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
        ats.append(_at(ev))
        if kind == "Full time":
            break  # both sides log the whistle
    for m, (period, t), nxt in zip(moments, ats, [*ats[1:], None], strict=False):
        later = ((p, s, b) for p, s, b in _plays(events) if p == period and s >= t + BALL_AFTER_S)
        p, s, ball = next(later, (0, 0, None))
        # only what is known by the ball's own time: no key moment came before it (A-1.4)
        if ball and (nxt is None or (p, s) < nxt):
            m["ball"] = ball
    return moments


# the ball between key moments (#205): who has it a beat after a moment
BALL_AFTER_S = 20


def _at(ev: dict) -> tuple[int, int]:
    """(period, seconds on the match clock) of an event."""
    minute, second = int(_num(ev.get("minute")) or 0), int(_num(ev.get("second")) or 0)
    return _num(ev.get("period")) or 0, minute * 60 + second


def _plays(events: list[dict]):
    """(period, second, snapshot) for each pass or carry by the side in possession: StatsBomb puts
    its location in that side's frame, attacking towards x = 120."""
    for ev in events:
        loc = ev.get("location") if isinstance(ev.get("location"), list) else []
        team = _name(ev.get("team"))
        if _name(ev.get("type")) not in ("Pass", "Carry"):
            continue
        if team != _name(ev.get("possession_team")):
            continue
        if len(loc) < 2 or _num(loc[0]) is None or _num(loc[1]) is None:
            continue
        p, s = _at(ev)
        clock = f"{s // 60:02d}:{s % 60:02d}"
        yield p, s, {"clock": clock, "team": _side(team), "x": loc[0], "y": loc[1]}


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


# --- f1 -----------------------------------------------------------------------------------

OPENF1 = "https://api.openf1.org/v1"
F1_ENDPOINTS = (
    "drivers",
    "position",
    "intervals",
    "pit",
    "stints",
    "laps",
    "race_control",
)
F1_TOP = 3  # overtakes and lead changes are called in the top three
F1_FIELD = 5  # pit stops of the top five; the standing gives the top five with gaps
F1_PIT_WINDOW = 40.0  # s: a place changing hands while either car is in the pits is a pit cycle
F1_FLAP = 10.0  # s: a pass that undoes one this recent is a car taking its place back
F1_HOLD = 20.0  # s: a pass is called once it has held this long (and any pit row behind it is in)
F1_PIT_MAX = 120.0  # s in the pit lane: longer is a car parked under a red flag, not a stop


def openf1(endpoint: str, session_key: str) -> list[dict]:
    if not session_key.isdigit():
        raise KeyError(session_key)
    name = f"of1_{endpoint}_{session_key}.json"
    if not (CACHE / name).exists():
        time.sleep(0.4)  # OpenF1 allows 3 requests a second
    rows = json.loads(_fetch(f"{OPENF1}/{endpoint}?session_key={session_key}", name))
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _when(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def f1_header(session_key: str, meta: dict | None = None) -> dict:
    """The event, date and race distance from meta. Never the result."""
    meta = meta or {}
    return {
        "sport": "f1",
        "match_id": _s(session_key),
        "competition": "Formula 1",
        "stage": _s(meta.get("stage")),
        "date": _s(meta.get("date"), 10),
        "laps": _num(meta.get("laps")) or 0,
    }


def _gap(value) -> str:
    return f"{value:.1f} seconds" if _num(value) is not None else _s(value, 12)  # not "+3.3s"


def f1_moments(header: dict, rows: dict[str, list[dict]]) -> list[dict]:
    """Moments from OpenF1 rows ({endpoint: rows}), each with the lap and the top five then.

    No look-ahead (A-1.4): a moment's clock is the latest feed time it reads. Rows count as known
    at their `date` (laps at `date_start`; their duration is never read), and a pit row's
    duration and new tyre once the car leaves the pit lane, `date` + `pit_duration`."""
    drivers = {}
    for d in rows.get("drivers") or []:
        if (n := _num(d.get("driver_number"))) is not None:
            name = _s(f"{d.get('first_name') or ''} {d.get('last_name') or ''}")
            drivers[n] = (name or _s(d.get("full_name")) or f"car {n}", _s(d.get("team_name")))

    def who(n) -> str:
        return drivers.get(n, (f"car {n}" if n is not None else "", ""))[0]

    def timed(kind: str, value: str, *fields: str) -> list[tuple]:
        out = []
        for r in rows.get(kind) or []:
            t = _when(r.get(value))
            if t is not None:
                out.append((t, *(r.get(f) for f in fields)))
        return sorted(out, key=lambda x: x[0])

    positions = [x for x in timed("position", "date", "driver_number", "position") if _num(x[2])]
    gaps = timed("intervals", "date", "driver_number", "gap_to_leader")
    laps = [x for x in timed("laps", "date_start", "driver_number", "lap_number") if _num(x[2])]
    control = timed("race_control", "date", "category", "flag", "message")
    pits = timed("pit", "date", "driver_number", "lap_number", "pit_duration")
    stints = [r for r in rows.get("stints") or [] if _num(r.get("lap_start"))]
    total = header.get("laps") or max((x[2] for x in laps), default=0)
    start = next((x[0] for x in control if _s(x[3]) == "SESSION STARTED"), None)
    if start is None:
        start = laps[0][0] if laps else None
    if start is None:
        return []

    def lap_at(t) -> int:
        return max((x[2] for x in laps if x[0] <= t), default=1)

    def order_at(t) -> dict:
        pos = {}
        for when, n, p in positions:
            if when > t:
                break
            pos[n] = p
        return pos

    def in_lane(t) -> set:
        """Cars in the pit lane at t whose new place the position feed has not sent yet."""
        out, window = set(), timedelta(seconds=F1_PIT_WINDOW)
        for when, n, _, lane in pits:  # its lane time is known only once it is out: capped
            out_at = when + min(timedelta(seconds=_num(lane) or F1_PIT_WINDOW), window)
            if when <= t <= out_at and not any(
                m == n and when - window <= w <= t for w, m, _ in positions
            ):
                out.add(n)
        return out

    def standing(t) -> dict:
        gap, lane = {}, in_lane(t)
        for when, n, g in gaps:
            if when > t:
                break
            gap[n] = g
        top, pitting_now, ahead = [], [], 0.0
        for p, n in sorted((p, n) for n, p in order_at(t).items())[:F1_FIELD]:
            if n in lane:  # its place is unknown until the feed sends it: never read ahead
                pitting_now.append({"pos": None, "driver": who(n), "gap": "in the pit lane"})
                continue
            g = gap.get(n)
            if _num(g) is not None:  # behind the car ahead or it lags a pit stop: left out
                g, ahead = (g if g > ahead else None), max(ahead, g)
            top.append({"pos": p, "driver": who(n), "gap": "leader" if p == 1 else _gap(g)})
        return {"lap": lap_at(t), "laps": total, "top": top + pitting_now}

    def pitting(n, since, t) -> bool:
        return any(p == n and since <= when <= t for when, p, *_ in pits)

    events = []  # (time called, type, outcome, driver number, players, detail)
    grid = order_at(start)
    pole = min(grid, key=grid.get, default=None)
    events.append((start, "Lights out", "race start", pole, {"leader": who(pole)}, {}))

    # overtakes and lead changes: a car moving up into the top three past the car that held it
    # OpenF1 sends both cars of a pass with one timestamp, so compare whole timestamps; the
    # passed car can also drop a few seconds before the other moves up, so dropped places are kept
    held, passes, dropped = dict(grid), [], {}
    flap = timedelta(seconds=F1_FLAP)
    for when, group in groupby((x for x in positions if x[0] > start), key=lambda x: x[0]):
        before = dict(held)
        held.update({n: p for _, n, p in group})
        for n, p in held.items():
            if p <= F1_TOP and p < before.get(n, p):
                passed = next((m for m, q in before.items() if q == p and m != n), None)
                if passed is None and p in dropped and when - dropped[p][1] <= flap:
                    passed = dropped[p][0]
                if passed is not None and held.get(passed, 0) >= p:  # it may move a beat later
                    passes.append((when, n, passed, p))
        dropped.update({q: (m, when) for m, q in before.items() if held[m] > q})

    def ahead(n, m, t) -> bool:
        order = order_at(t)
        return order.get(n, 99) < order.get(m, 99)

    hold, window = timedelta(seconds=F1_HOLD), timedelta(seconds=F1_PIT_WINDOW)
    for when, n, passed, p in passes:
        at = when + hold  # called once it has held, so the hold is never read ahead
        # timing noise: a place handed straight back, or a car only taking its place back
        undone = any(m == passed and o == n and when < w <= at for w, m, o, _ in passes)
        if undone or not ahead(n, passed, at) or ahead(n, passed, when - flap):
            continue
        pit = pitting(n, when - window, at) or pitting(passed, when - window, at)
        if pit and p > 1:  # places swapped by stops below the lead are not overtakes
            continue
        outcome = f"P{p} " + ("in the pit stops" if pit else "on track")
        kind = "Lead change" if p == 1 else "Overtake"
        events.append((at, kind, outcome, n, {"driver": who(n), "passed": who(passed)}, {}))

    for when, n, lap, lane in pits:
        lane = _num(lane)  # pit entry to exit, not the stationary stop
        if order_at(when).get(n, 99) > F1_FIELD or not lane or lane > F1_PIT_MAX:
            continue
        stay = timedelta(seconds=lane)  # a red flag within its lane time: a tyre change, not a stop
        if any(_s(f) == "RED" and when - stay <= w <= when + stay for w, _, f, _ in control):
            continue
        lap = _num(lap) or 0
        tyre = next(
            (
                _s(r.get("compound")).lower()
                for r in stints
                if r.get("driver_number") == n and r.get("lap_start") == lap + 1
            ),
            "",
        )
        detail = {"tyres": tyre, "pit_lane_time": f"{lane:.1f} seconds in the pit lane"}
        outcome = f"pits for {tyre} tyres" if tyre else "pit stop"
        # called as it leaves the pit lane: its time there and new tyre are known only then
        exit_ = when + timedelta(seconds=lane)
        events.append((exit_, "Pit stop", outcome, n, {"driver": who(n)}, detail))

    for when, category, flag, message in control:
        message = _s(message, 80)
        if _s(category) == "SafetyCar" and ("DEPLOYED" in message or "ENDING" in message):
            kind = "Safety car"
        elif _s(flag) == "RED":
            kind = "Red flag"
        elif message == "LOW GRIP CONDITIONS":
            kind = "Conditions"
        else:
            continue
        events.append((when, kind, message.capitalize(), None, {}, {}))

    # no retirements: OpenF1 sends no row confirming one, and a car's missing laps can be a slow
    # car's later rows, so inferring it would read ahead (A-1.4)

    final = next((x[0] for x in laps if x[2] == total), None)
    if final is not None:
        leader = min(order_at(final).items(), key=lambda x: x[1], default=(None, 0))[0]
        events.append((final, "Last lap", "final lap", leader, {"leader": who(leader)}, {}))
    flag = next((x[0] for x in control if _s(x[2]) == "CHEQUERED"), None)
    if flag is not None:  # called once the cars behind have crossed and their gaps are in
        at = flag + hold
        winner = min(order_at(at).items(), key=lambda x: x[1], default=(None, 0))[0]
        events.append((at, "Finish", "chequered flag", winner, {"winner": who(winner)}, {}))

    moments = []
    for when, kind, outcome, n, players, detail in sorted(events, key=lambda e: e[0]):
        secs = int((when - start).total_seconds())
        moments.append(
            {
                "sport": "f1",
                "match_id": header["match_id"],
                "idx": len(moments),
                "period": lap_at(when),
                "clock": f"{secs // 60:02d}:{secs % 60:02d}",
                "type": kind,
                "team": drivers.get(n, ("", ""))[1],
                "players": {k: v for k, v in players.items() if v},
                "outcome": outcome,
                "score": standing(when),
                "detail": {k: v for k, v in detail.items() if v not in ("", None)},
            }
        )
    return moments


def load(sport: str, match_id: str, meta: dict | None = None) -> tuple[dict, list[dict]]:
    """(header, moments) for one match. Football needs its StatsBomb match record as meta;
    basketball takes competition, stage and date from meta; f1 its stage, date and laps."""
    if sport == "football":
        header = football_header(meta or {"match_id": match_id})
        events, nicknames = statsbomb_events(match_id), statsbomb_nicknames(match_id)
        return header, football_moments(header, events, nicknames)
    if sport == "basketball":
        rows = nba_rows(match_id)
        header = basketball_header(match_id, rows, meta)
        return header, basketball_moments(header, rows)
    if sport == "f1":
        header = f1_header(match_id, meta)
        return header, f1_moments(header, {e: openf1(e, match_id) for e in F1_ENDPOINTS})
    match = cricsheet_match(match_id)
    header = cricket_header(match_id, match)
    return header, cricket_moments(header, match)
