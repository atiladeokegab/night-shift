"""GET /teams/{sport}/{match_id}: each side's form, the head-to-head and the squad, as of the
match's start (#375). Read from the graph (core/graph.py); a section the graph can't give is empty,
and the page shows what is there. Cached 60 s per match: the service has one vCPU."""

import time

from fastapi import APIRouter, HTTPException

from core import graph
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


def build(sport: str, header: dict) -> dict:
    before = header["date"]
    sides = [header[k] for k in ("home", "away") if k in header]  # a race has no sides
    return {
        "teams": [
            {
                "team": t,
                "form": _ask("team_form", sport, t, before),
                "squad": _ask("squad", sport, t, before)[:SQUAD_MAX],
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
