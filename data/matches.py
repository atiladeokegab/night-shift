"""Bundled matches for the server and the smoke: data/sample/<sport>-<match_id>.json.

Each file holds {"header": ..., "moments": [...]} made by agent.feed, so a replay needs no network.
Rebuild with: uv run python -m data.matches
"""

from __future__ import annotations

import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parent / "sample"
VIDEO = Path(__file__).resolve().parent / "video"
VIDEO_LEAD_S = 5  # the video starts this long before its first mapped moment


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
        if vmap := video_map(h["match_id"]):
            match["youtube_id"] = vmap["youtube_id"]
            match["video_start"] = vmap["start"]
        out.append(match)
    return out


def load_moments(match_id: str) -> list[dict]:
    return _read(match_id)["moments"]


def video_map(match_id: str) -> dict | None:
    """data/video/<sport>-<match_id>.json: {youtube_id, source, moments: [{idx, video_t}]}, plus
    `start`: the whole second the page starts the video at, just before its first mapped moment."""
    match_id = str(match_id)
    found = sorted(VIDEO.glob(f"*-{match_id}.json")) if match_id.isalnum() else []
    if not found:
        return None
    vmap = json.loads(found[0].read_text(encoding="utf-8"))
    return {**vmap, "start": max(0, int(vmap["moments"][0]["video_t"]) - VIDEO_LEAD_S)}


def match_header(match_id: str) -> dict:
    return _read(match_id)["header"]


def _bundle(sport: str, match_id: str, meta: dict | None = None) -> None:
    from agent import feed

    header, moments = feed.load(sport, match_id, meta)
    path = SAMPLE / f"{sport}-{match_id}.json"
    path.write_text(
        json.dumps({"header": header, "moments": moments}, ensure_ascii=False, indent=1)
    )


if __name__ == "__main__":
    from agent import feed

    final = next(m for m in feed.statsbomb_matches(72, 107) if m["match_id"] == 3906390)
    _bundle("football", "3906390", final)  # 2023 Women's World Cup final
    final = next(m for m in feed.statsbomb_matches(43, 106) if m["match_id"] == 3869685)
    _bundle("football", "3869685", final)  # 2022 World Cup final, Messi v Mbappé
    _bundle("cricket", "1298150")  # India v Pakistan, T20 World Cup 2022
    finals = {"competition": "NBA Finals", "stage": "Game 6", "date": "1998-06-14"}
    _bundle("basketball", "0049700088", finals)  # Jordan's last shot as a Bull
    season = {"competition": "NBA", "stage": "Regular season", "date": "2006-01-22"}
    _bundle("basketball", "0020500591", season)  # Kobe's 81 v Toronto
    race = {"stage": "British Grand Prix, Silverstone", "date": "2024-07-07", "laps": 52}
    _bundle("f1", "9558", race)  # Hamilton's 2024 British Grand Prix win
