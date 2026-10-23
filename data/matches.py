"""Bundled matches for the server and the smoke: data/sample/<sport>-<match_id>.json.

Each file holds {"header": ..., "moments": [...]} made by agent.feed, so a replay needs no network.
Rebuild with: uv run python -m data.matches
"""

from __future__ import annotations

import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parent / "sample"


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
        title = f"{h['home']} v {h['away']}, {h['competition']} {h['stage']}".strip()
        out.append({"match_id": h["match_id"], "sport": h["sport"], "title": title, "sample": True})
    return out


def load_moments(match_id: str) -> list[dict]:
    return _read(match_id)["moments"]


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
    _bundle("cricket", "1298150")  # India v Pakistan, T20 World Cup 2022
