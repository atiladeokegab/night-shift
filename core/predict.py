"""Predictions (#119): a player's pre-match record blended with this match so far, from the packs.

Pure functions of (pack, moments, idx). A pack's `tonight` holds the whole match, so every function
first keeps only what moments[idx], the moment on screen, has revealed. The numbers are counts,
rates and a Beta-binomial blend, and every answer cites them.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

PACKS = Path(__file__).resolve().parent.parent / "data" / "packs"
SHOTS = ("basketball", "football")  # cricket has no shot locations: phase rates instead
PRIOR = 10  # in every blend the prior is worth this many attempts (or balls)
SMALL = 10  # fewer pre-match attempts (or balls) than this is a small sample, and the text says so
TOP = 3  # players named per team in the odds


def load_pack(sport: str, match_id: str) -> dict | None:
    """data/packs/<sport>-<match_id>.json, or None when the match has no pack."""
    sport, match_id = str(sport), str(match_id)
    path = PACKS / f"{sport}-{match_id}.json"
    if not (sport.isalnum() and match_id.isalnum() and path.exists()):  # ids may come from a URL
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _so_far(pack: dict, moments: list, idx: int) -> list[dict]:
    """The match's own shots or balls that moments[idx] has revealed: never a later one."""
    if not 0 <= idx < len(moments):
        raise ValueError(f"no moment {idx}")
    now = moments[idx]["idx"]
    return [t for t in pack["tonight"] if t["idx"] <= now]


def _fold(s: str) -> str:
    """Lower case without accents, so "Mbappe" finds "Kylian Mbappé"."""
    s = unicodedata.normalize("NFKD", " ".join(str(s).split()))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def find(pack: dict, name: str) -> str:
    """The pack's name for `name`: the full name, else every word of it ("kobe"), else a substring,
    else the surname ("Virat Kohli" finds "V Kohli"). KeyError when nobody matches."""
    want = _fold(name)
    words = want.split()
    names = list(pack["players"])
    for match in (
        lambda n: _fold(n) == want,
        lambda n: all(w in _fold(n).split() for w in words),
        lambda n: want in _fold(n),
        lambda n: words[-1] in _fold(n).split(),
    ):
        hits = [n for n in names if words and match(n)]
        if hits:
            return max(hits, key=lambda n: pack["players"][n].get("games", 0))
    raise KeyError(name)


def _blend(hits: float, n: int, prior: float) -> float:
    """Beta-binomial posterior mean: `hits` in `n` on top of `prior` worth PRIOR attempts."""
    return (hits + PRIOR * prior) / (n + PRIOR)


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def _team_rate(pack: dict, team: str) -> float:
    t = pack["teams"].get(team) or {}
    return t["made"] / t["attempts"] if t.get("attempts") else 0.0


def _key(pack: dict) -> str:
    """What a shot is worth: a make in basketball, its xG in football."""
    return "xg" if pack["sport"] == "football" else "made"


def _rate(pack: dict, p: dict, shots: list[dict]) -> float:
    """Chance one of this player's shots goes in: the pre-match rate shrunk to the team's, then
    blended with tonight's shots so far."""
    key = _key(pack)
    before = _blend(p.get(key, 0), p["attempts"], _team_rate(pack, p["team"]))
    return _blend(sum(t[key] for t in shots), len(shots), before)


def shot_points(pack: dict, moments: list, idx: int, name: str) -> dict:
    """Shot-map dots for one player: pre-match (season) and tonight up to moments[idx], plus the
    pre-match zone rates. ValueError for cricket or a bad idx, KeyError for an unknown player."""
    if pack["sport"] not in SHOTS:
        raise ValueError(f"no shot locations for {pack['sport']}")
    so_far = _so_far(pack, moments, idx)
    name = find(pack, name)
    p = pack["players"][name]
    zones = sorted(p["zones"].items(), key=lambda z: -z[1]["att"])
    return {
        "player": name,
        "sport": pack["sport"],
        "season": [
            {"x": float(s["x"]), "y": float(s["y"]), "made": s["made"], "zone": s["zone"]}
            for s in p["shots"]
        ],
        "tonight": [
            {"x": float(t["x"]), "y": float(t["y"]), "made": t["made"], "idx": t["idx"]}
            for t in so_far
            if t["player"] == name
        ],
        "zones": [
            dict(zone=z, attempts=c["att"], made=c["made"], rate=round(c["made"] / c["att"], 3))
            for z, c in zones
        ],
    }


def next_score_odds(pack: dict, moments: list, idx: int) -> dict[str, list[dict]]:
    """Per team, each player's chance of scoring the team's next basket or goal: their share of
    the team's attempts (pre-match, blended with tonight) times their rate. Sums to 1 per team."""
    if pack["sport"] not in SHOTS:
        raise ValueError(f"no next-to-score odds for {pack['sport']}")
    so_far = _so_far(pack, moments, idx)
    out = {}
    for team, totals in pack["teams"].items():
        roster = {n: p for n, p in pack["players"].items() if p["team"] == team}
        mine = [t for t in so_far if t["player"] in roster]
        rows = []
        for n, p in roster.items():
            shots = [t for t in mine if t["player"] == n]
            if not (p["attempts"] or shots):
                continue
            before = p["attempts"] / totals["attempts"] if totals["attempts"] else 0
            share = _blend(len(shots), len(mine), before)
            rate = _rate(pack, p, shots)
            rows.append(
                {
                    "player": n,
                    "p": share * rate,
                    "before": p["attempts"],
                    "share_before": before,
                    "tonight": len(shots),
                    "tonight_team": len(mine),
                    "rate": rate,
                }
            )
        total = sum(r["p"] for r in rows)
        if total:
            for r in rows:
                r["p"] /= total
            out[team] = sorted(rows, key=lambda r: -r["p"])
    return out


def odds_text(pack: dict, moments: list, idx: int) -> str:
    """get_next_score_odds, as the commentator reads it."""
    if pack["sport"] not in SHOTS:
        return "Next-to-score odds are for basketball and football; ask for a player's profile."
    football = pack["sport"] == "football"
    lines = [
        "Next to score for each team: share of the team's attempts (before tonight, blended with "
        f"tonight) times the {'xG per shot' if football else 'make rate'}."
    ]
    for team, rows in next_score_odds(pack, moments, idx).items():
        said = []
        for r in rows[:TOP]:
            small = ", small sample" if r["before"] < SMALL else ""
            rate = f"xG {r['rate']:.2f} per shot" if football else f"makes {_pct(r['rate'])}"
            said.append(
                f"{r['player']} {_pct(r['p'])} ({_pct(r['share_before'])} of attempts before "
                f"tonight, {r['tonight']} of {r['tonight_team']} tonight, {rate}{small})"
            )
        lines.append(f"{team}: " + "; ".join(said))
    return "\n".join(lines)


def _shots_profile(pack: dict, so_far: list[dict], name: str) -> str:
    p, w = pack["players"][name], pack["window"]
    mine = [t for t in so_far if t["player"] == name]
    football = pack["sport"] == "football"
    what = "shots" if football else "attempts"
    head = f"{name} ({p['team']}), before tonight ({w['from']} to {w['to']}, {p['games']} games): "
    if football:
        head += f"{p['made']} goals from {p['attempts']} shots, {p['xg']} xG"
    else:
        head += f"made {p['made']} of {p['attempts']}" + (
            f" ({_pct(p['made'] / p['attempts'])})" if p["attempts"] else ""
        )
    if p["attempts"] < SMALL:
        head += f"; small sample ({p['attempts']} {what})"
    lines = [head + "."]
    before = _rate(pack, p, [])
    order = sorted(p["zones"], key=lambda z: -p["zones"][z]["att"]) + [t["zone"] for t in mine]
    for z in dict.fromkeys(order):
        c = p["zones"].get(z) or {"att": 0, "made": 0}
        here = [t for t in mine if t["zone"] == z]
        made = sum(t["made"] for t in here)
        rate = _blend(made, len(here), _blend(c["made"], c["att"], before))
        pre = f"{c['made']} of {c['att']}"
        pre += f" ({_pct(c['made'] / c['att'])})" if c["att"] else ""
        now = f", {made} of {len(here)} tonight" if here else ""
        lines.append(f"- {z}: {pre} before tonight{now}; blended {_pct(rate)}")
    made = sum(t["made"] for t in mine)
    tonight = f"Tonight so far: {made} of {len(mine)} {what}"
    if football:
        tonight += f", {sum(t['xg'] for t in mine):.2f} xG"
    chance = "Chance a shot goes in (xG-based)" if football else "Blended make rate"
    lines.append(f"{tonight}. {chance}: {_pct(_rate(pack, p, mine))}.")
    return "\n".join(lines)


def _cricket_profile(pack: dict, so_far: list[dict], name: str) -> str:
    p, w = pack["players"][name], pack["window"]
    head = f"{name} ({p['team']}), before tonight ({w['from']} to {w['to']}, {p['games']} games)."
    lines = [head]
    for ph in ("powerplay", "middle", "death"):
        b = p["batting"].get(ph) or {"balls": 0, "runs": 0, "outs": 0}
        # shortcut: tonight's runs are the ball's total (extras too) and a wide counts as faced;
        # the pack keeps no extras for tonight, add them there if this misleads
        here = [t for t in so_far if t["batter"] == name and t["phase"] == ph]
        runs, outs = sum(t["runs"] for t in here), sum(t["out"] == name for t in here)
        if not (b["balls"] or here):
            continue
        sr = _blend(runs, len(here), b["runs"] / b["balls"] if b["balls"] else 0) * 100
        small = ", small sample" if b["balls"] < SMALL else ""
        lines.append(
            f"- Batting, {ph}: {b['runs']} off {b['balls']} balls, out {b['outs']} times before "
            f"tonight{small}; {runs} off {len(here)}, out {outs} tonight; "
            f"blended strike rate {round(sr)}"
        )
    bw = p["bowling"]
    here = [t for t in so_far if t["bowler"] == name]
    if bw["balls"] or here:
        small = ", small sample" if bw["balls"] < SMALL else ""
        econ = f"economy {bw['economy']}" if bw["economy"] is not None else "no economy yet"
        lines.append(
            f"- Bowling: {bw['wickets']} wickets in {bw['balls']} balls, {econ} before tonight"
            f"{small}; {sum(t['runs'] for t in here)} runs and "
            f"{sum(bool(t['out']) for t in here)} wickets off {len(here)} balls tonight"
        )
    if len(lines) == 1:
        lines.append("No batting or bowling on record yet.")
    return "\n".join(lines)


def profile_text(pack: dict, moments: list, idx: int, name: str) -> str:
    """get_player_profile, as the commentator reads it."""
    so_far = _so_far(pack, moments, idx)
    try:
        name = find(pack, name)
    except KeyError:
        return f"No pre-match record for {name or 'that player'} in this match."
    if pack["sport"] == "cricket":
        return _cricket_profile(pack, so_far, name)
    return _shots_profile(pack, so_far, name)
