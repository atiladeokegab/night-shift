"""Bundled matches for the server and the smoke: data/sample/<sport>-<match_id>.json.

Each file holds {"header": ..., "moments": [...]} made by agent.feed, so a replay needs no network.
Rebuild with: uv run python -m data.matches
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

SAMPLE = Path(__file__).resolve().parent / "sample"
VIDEO = Path(__file__).resolve().parent / "video"
VIDEO_LEAD_S = 10  # the video starts this long before its first mapped moment: time for v3
# StatsBomb's women's sides: "Bristol City WFC", "Spain Women's"; said "Bristol City", "Spain"
CLUB_SUFFIX = re.compile(r"\s+(?:WFC|LFC|FC|Women's|Women)$", re.I)
# "Jump to the big moment" (#163): the moment each jump starts at, a beat before its peak.
PEAKS = {
    "0020500591": 22,  # Kobe: free throws for 80 and 81
    "0049700088": 31,  # Jordan's steal, then the shot
    "1298150": 48,  # the last over
    "1515217": 57,  # Nepal's last over: 13 to win
    "3869685": 59,  # the World Cup final shoot-out
    "3754092": 37,  # Hazard's equaliser
    "3913122": 33,  # the 82nd-minute equaliser, then the 94th-minute winner
    "7457": 37,  # Orlando's 82nd-minute equaliser, then the 89th-minute own goal
    "9636": 12,  # Verstappen into P1
}


def _path(match_id: str) -> Path:
    found = sorted(SAMPLE.glob(f"*-{match_id}.json")) if match_id.isalnum() else []
    if not found:  # an id from a request is untrusted: only plain ids reach the glob
        raise KeyError(match_id)
    return found[0]


def _read(match_id: str) -> dict:
    return json.loads(_path(str(match_id)).read_text(encoding="utf-8"))


def list_matches() -> list[dict]:
    out = []
    for path in sorted(SAMPLE.glob("*.json")):
        h = json.loads(path.read_text(encoding="utf-8"))["header"]
        sides = f"{h['home']} v {h['away']}, " if "home" in h else ""  # a race has no sides
        title = f"{sides}{h['competition']} {h['stage']}".strip()
        match = {"match_id": h["match_id"], "sport": h["sport"], "title": title, "sample": True}
        peak = PEAKS.get(h["match_id"])
        if peak is not None:
            match["peak_idx"] = peak
        if vmap := video_map(h["match_id"]):
            match["youtube_id"] = vmap["youtube_id"]
            match["video_start"] = vmap["start"]
            if peak is not None:
                match["peak_video_start"] = video_map(h["match_id"], peak)["start"]
            if vmap.get("embed") is False:  # owner blocks embedding: a poster and a link instead
                match["embed"] = False
        out.append(match)
    return out


def load_moments(match_id: str) -> list[dict]:
    data = _read(match_id)
    return _stated(data["header"], data["moments"])


def _stated(header: dict, moments: list[dict]) -> list[dict]:
    """Each moment with the numbers a climax line gets wrong said outright in its detail: a cricket
    chase's state (or its result), who leads a home/away game, and a basketball shooter's points
    milestone. Built from each moment's own score and the ones before it, so no later moment
    leaks in."""
    best: dict[str, int] = {}
    for m in moments:
        s, d = m["score"], m["detail"]
        if m["sport"] == "football" and "x" in m and "y" in m:
            d["where"] = _where(header, m)
        if "home" in s:  # without it a basket that cuts the lead is heard as taking it
            d["lead"] = _lead(header, m)
        if m["sport"] == "cricket" and "target" in s and "balls_left" in d:
            d["chase"] = _chase(header, m)
        pts, who = d.get("player_points"), (m["players"] or {}).get("shooter")
        if m["sport"] == "basketball" and pts is not None and who:
            before = best.get(who, 0)
            if pts >= 50 or (pts >= 30 and pts // 10 > before // 10):
                d["milestone"] = f"{who} has {pts} points tonight"
            best[who] = max(before, pts)
    return moments


def _where(header: dict, m: dict) -> str:
    """Where a football moment happened, in spoken words (#172). StatsBomb's pitch is 120 x 80 yd,
    and the event's own team attacks towards x = 120, so y < 40 is that team's left. A zone names
    whose box or half it is: for a foul, the moment's team is the offender's."""
    x, y = m["x"], m["y"]
    left, wide, central = y < 40, y < 18 or y > 62, abs(y - 40) < 4
    if m["type"] == "Shot":
        yards = max(1, round(math.hypot(120 - x, 40 - y)))  # a tap-in is "from 1 yard"
        side = (
            f"wide on the {'left' if left else 'right'}"
            if wide
            else ("central" if central else f"{'left' if left else 'right'} of centre")
        )
        return f"from {yards} yard{'s' * (yards != 1)}, {side}"
    own, other = m["team"], header["away"] if m["team"] == header["home"] else header["home"]
    own, other = CLUB_SUFFIX.sub("", own), CLUB_SUFFIX.sub("", other)
    if x >= 114 and 30 <= y <= 50:
        return f"inside {other}'s six-yard box"
    if x > 104 and not wide:
        return f"inside {other}'s box"
    if x >= 99 and not wide:
        return f"on the edge of {other}'s box"
    if x <= 18 and not wide:
        return f"inside {own}'s own box"
    if x < 60:
        return f"in {own}'s own half"
    return f"on the {'left' if left else 'right'} wing" if wide else f"in {other}'s half"


def balls(match_id: str) -> dict[int, dict]:
    """Who has the ball a beat after each football moment (#205), by the moment's idx. Kept out of
    the moments: a moment published at its own time must not carry play from after it (A-1.4)."""
    return {b["after_idx"]: b for b in _read(match_id).get("balls", [])}


def orientation(header: dict, past: list[dict], b: dict) -> str:
    """Who has the ball (`b`, from balls()) in the gap after the last of the `past` football
    moments (#205), and the score when that moment changed it. StatsBomb gives a side's attack
    only as towards x = 120: the line says whose goal they attack, never left or right."""
    m, before = past[-1], past[-2] if len(past) > 1 else None
    other = header["away"] if b["team"] == header["home"] else header["home"]
    team, other = CLUB_SUFFIX.sub("", b["team"]), CLUB_SUFFIX.sub("", other)
    where = _where(header, {"type": "Pass", **b}).replace(f"{team}'s own", "their own")
    text = f"{team} have the ball {where}, attacking {other}'s goal."
    if before and before["score"] != m["score"] and "lead" in m["detail"]:
        text += f" {m['detail']['lead'][0].upper()}{m['detail']['lead'][1:]}."
    return text


def leader(m: dict) -> str | None:
    """Who leads after a home/away moment, "home", "away" or None when level; a shootout decides
    once the goals are level."""
    s, so = m["score"], m["detail"].get("shootout")
    h, a = (so["home"], so["away"]) if so and s["home"] == s["away"] else (s["home"], s["away"])
    return "home" if h > a else "away" if a > h else None


def _lead(header: dict, m: dict) -> str:
    s, so = m["score"], m["detail"].get("shootout")
    shootout = " the shootout" if so and s["home"] == s["away"] else ""
    h, a = (so["home"], so["away"]) if shootout else (s["home"], s["away"])
    side = leader(m)
    if side is None:
        return f"level at {h}-{a}" + (" in the shootout" if shootout else "")
    return f"{CLUB_SUFFIX.sub('', header[side])} lead{shootout} {max(h, a)}-{min(h, a)}"


def _chase(header: dict, m: dict) -> str:
    s, left, team = m["score"], m["detail"]["balls_left"], m["team"]
    need = s["target"] - s["runs"]
    if need <= 0:
        return f"{team} win by {10 - s['wickets']} wickets"
    if left == 0 or s["wickets"] == 10:
        other = header["home"] if team == header["away"] else header["away"]
        return "the match is tied" if need == 1 else f"{other} win by {need - 1} runs"
    runs = f"{need} run{'s' * (need > 1)}"
    balls = "the final ball" if left == 1 else f"the last {left} balls"
    return f"{team} need {runs} from {balls}"


def video_map(match_id: str, start_idx: int | None = None) -> dict | None:
    """data/video/<sport>-<match_id>.json: {youtube_id, embed?, source, moments: [{idx, video_t}]},
    plus `start`: the whole second the page starts the video at, just before its first mapped
    moment (from `start_idx` on, for a replay that jumps to a moment)."""
    match_id = str(match_id)
    found = sorted(VIDEO.glob(f"*-{match_id}.json")) if match_id.isalnum() else []
    if not found:
        return None
    vmap = json.loads(found[0].read_text(encoding="utf-8"))
    first = next((m for m in vmap["moments"] if m["idx"] >= (start_idx or 0)), vmap["moments"][-1])
    return {**vmap, "start": max(0, int(first["video_t"]) - VIDEO_LEAD_S)}


def match_header(match_id: str) -> dict:
    return _read(match_id)["header"]


def _bundle(sport: str, match_id: str, meta: dict | None = None) -> None:
    from agent import feed

    header, moments = feed.load(sport, match_id, meta)
    path = SAMPLE / f"{sport}-{match_id}.json"
    found = [{"after_idx": m["idx"], **m.pop("ball")} for m in moments if "ball" in m]
    rows = ",\n".join(json.dumps(m, ensure_ascii=False) for m in moments)  # one moment per line
    head = json.dumps(header, ensure_ascii=False)
    body = f'{{"header": {head},\n "moments": [\n{rows}\n]'
    if found:  # who has the ball between moments (#205), one per line
        body += ',\n "balls": [\n' + ",\n".join(json.dumps(b, ensure_ascii=False) for b in found)
        body += "\n]"
    path.write_text(body + "}\n", encoding="utf-8")


if __name__ == "__main__":
    from agent import feed

    bridge = next(m for m in feed.statsbomb_matches(2, 27) if m["match_id"] == 3754092)
    _bundle("football", "3754092", bridge)  # Chelsea 2-2 Tottenham, 2016: Leicester win the league
    final = next(m for m in feed.statsbomb_matches(43, 106) if m["match_id"] == 3869685)
    _bundle("football", "3869685", final)  # 2022 World Cup final, Messi v Mbappé
    wsl = next(m for m in feed.statsbomb_matches(37, 281) if m["match_id"] == 3913122)
    _bundle("football", "3913122", wsl)  # Brighton 3-2 Bristol City, WSL 2024: the long tail
    nwsl = next(m for m in feed.statsbomb_matches(49, 3) if m["match_id"] == 7457)
    _bundle("football", "7457", nwsl)  # Orlando 3-4 North Carolina, NWSL 2018: called whole
    _bundle("cricket", "1298150")  # India v Pakistan, T20 World Cup 2022
    _bundle("cricket", "1515217")  # Netherlands v Nepal, Women's T20 World Cup Qualifier: whole
    finals = {"competition": "NBA Finals", "stage": "Game 6", "date": "1998-06-14"}
    _bundle("basketball", "0049700088", finals)  # Jordan's last shot as a Bull
    season = {"competition": "NBA", "stage": "Regular season", "date": "2006-01-22"}
    _bundle("basketball", "0020500591", season)  # Kobe's 81 v Toronto
    race = {"stage": "São Paulo Grand Prix, Interlagos", "date": "2024-11-03", "laps": 69}
    _bundle("f1", "9636", race)  # Verstappen from 17th to win in the rain, 2024
