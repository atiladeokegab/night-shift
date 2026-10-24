"""GET /teams/{sport}/{match_id}: each side's form, the head-to-head and the squad, as of the
match's start (#375). Read from the graph (core/graph.py); a section the graph can't give is empty,
and the page shows what is there. Cached 60 s per match: the service has one vCPU."""

import time

from fastapi import APIRouter, HTTPException

from core import graph
from core.predict import load_pack
from data.matches import match_header

TTL_S = 60.0
SQUAD_MAX = 8  # headline lines a screen reader can take in
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _ask(name: str, *args, **kw) -> list:
    """A graph function's rows, or [] when it is missing, off or fails: never an error."""
    fn = getattr(graph, name, None)
    try:
        return (fn and fn(*args, **kw)) or []
    except Exception:
        graph.log.error("%s failed", name, exc_info=False)
        return []


def _pack_squad(pack: dict | None, team: str) -> list[dict]:
    """The team's players from the match's pack, most scoring first, when the graph has no squad.
    A pack counts only matches before this one (its window), so nothing here is from tonight."""
    mine = [(n, p) for n, p in ((pack or {}).get("players") or {}).items() if p.get("team") == team]
    mine.sort(key=lambda kv: (-kv[1].get("made", 0), -kv[1].get("games", 0), kv[0]))
    what = "goals from" if (pack or {}).get("sport") == "football" else "baskets from"
    return [
        {
            "name": n,
            "matches": p["games"],
            "headline": f"{p['made']} {what} {p['attempts']} shots in {p['games']}",
        }
        for n, p in mine[:SQUAD_MAX]
        if p.get("games") and p.get("attempts")
    ]


def build(sport: str, header: dict) -> dict:
    before = header["date"]
    sides = [header[k] for k in ("home", "away") if k in header]  # a race has no sides
    squads = {t: _ask("squad", sport, t, before)[:SQUAD_MAX] for t in sides}
    if not all(squads.values()):  # the graph lacks a side's squad: the packs, once, for this match
        pack = graph.pack(header["match_id"]) or load_pack(sport, header["match_id"])
        squads = {t: sq or _pack_squad(pack, t) for t, sq in squads.items()}
    return {
        "teams": [
            {
                "team": t,
                "form": _ask("team_form", sport, t, before),
                "squad": squads[t],
                "note": None if squads[t] else _ask("first_match", sport, t, before) or None,
            }
            for t in sides
        ],
        "head_to_head": _ask("head_to_head", sport, *sides, before) if len(sides) == 2 else [],
    }


router = APIRouter()


@router.get("/teams/{sport}/{match_id}")
def teams(sport: str, match_id: str):
    try:
        header = match_header(match_id)
    except KeyError as exc:
        raise HTTPException(404, f"no match {match_id!r}") from exc
    if header["sport"] != sport:
        raise HTTPException(404, f"match {match_id!r} is not {sport}")
    key, now = (sport, match_id), time.monotonic()
    if (hit := _cache.get(key)) and now - hit[0] < TTL_S:
        return hit[1]
    body = build(sport, header)
    _cache[key] = (now, body)
    return body
