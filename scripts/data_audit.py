"""Offline audit of the bundled data: where each match came from, and that it holds together.

    uv run python scripts/data_audit.py [--json]

Walks data/sample (made by agent/feed.py), data/packs and data/video; no network. Per match it
checks the shape agent/feed.py writes, that moments run in idx and clock order, that no side's
score goes backwards, and that every pack and video file names a bundled match. One row per match;
exit 1 on any failure. data/graph (SurrealDB's embedded store) is not read: that needs the engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.matches import PEAKS  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
# agent/feed.py's sources, one per sport; the header itself names none
SOURCE = {
    "football": "StatsBomb open data",
    "cricket": "Cricsheet",
    "basketball": "stats.nba.com play-by-play",
    "f1": "OpenF1",
}
MOMENT_KEYS = {"sport", "match_id", "idx", "period", "clock", "type", "team"}
MOMENT_KEYS |= {"players", "outcome", "score", "detail"}
HEADER_KEYS = {"sport", "match_id", "competition", "stage", "date"}
# Score fields that never fall within a period: a goal, a basket, a run, a wicket, a lap.
RISING = {
    "football": ("home", "away"),
    "basketball": ("home", "away"),
    "cricket": ("runs", "wickets"),
    "f1": ("lap",),
}


def _secs(clock: str) -> int:
    sign = -1 if clock.startswith("-") else 1  # F1's clock runs from the start, so may be < 0
    mins, secs = clock.lstrip("-").split(":")
    return sign * (int(mins) * 60 + int(secs))


def clock_key(sport: str, m: dict) -> tuple:
    """A moment's place in its match: later moments sort higher."""
    if sport == "cricket":  # "over.ball"
        over, ball = m["clock"].split(".")
        return (m["period"], int(over), int(ball))
    if sport == "basketball":  # a quarter's clock counts down
        return (m["period"], -_secs(m["clock"]))
    if sport == "f1":  # the period is the lap; the clock is the time since the start
        return (_secs(m["clock"]), m["period"])
    return (m["period"], _secs(m["clock"]))


def check_match(header: dict, moments: list[dict], name: str = "") -> list[str]:
    """Every failed invariant of one match, as short sentences; [] when it holds together."""
    sport, mid = header.get("sport"), header.get("match_id")
    fails = []
    need = HEADER_KEYS | ({"laps"} if sport == "f1" else {"home", "away"})
    if missing := need - header.keys():
        fails.append(f"header lacks {sorted(missing)}")
    if sport not in SOURCE:
        return [*fails, f"unknown sport {sport!r}"]
    if name and name != f"{sport}-{mid}.json":
        fails.append(f"file {name} is not {sport}-{mid}.json")
    if not moments:
        fails.append("no moments")
    for i, m in enumerate(moments):
        if missing := MOMENT_KEYS - m.keys():
            return [*fails, f"moment {i} lacks {sorted(missing)}"]
        if m["idx"] != i:
            fails.append(f"moment {i} has idx {m['idx']}")
        if (m["sport"], m["match_id"]) != (sport, mid):
            fails.append(f"moment {i} is {m['sport']} {m['match_id']}")
    keys = [clock_key(sport, m) for m in moments]
    fails += [
        f"moment {i} ({moments[i]['clock']}) is before moment {i - 1}"
        for i in range(1, len(keys))
        if keys[i] < keys[i - 1]
    ]
    for a, b in zip(moments, moments[1:], strict=False):
        if sport == "cricket" and a["period"] != b["period"]:
            continue  # a new innings starts from 0
        for side in RISING[sport]:
            if b["score"].get(side, 0) < a["score"].get(side, 0):
                fails.append(f"{side} falls at moment {b['idx']}: {a['score']} to {b['score']}")
    if sport == "f1" and any(m["score"].get("laps") != header.get("laps") for m in moments):
        fails.append("a moment's lap count is not the header's")
    return fails


def check_extra(kind: str, path: Path, samples: dict[str, dict]) -> list[str]:
    """A pack or video file: it names a bundled match, and stays inside it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    sport, mid = path.stem.split("-", 1)
    sample = samples.get(mid)
    if sample is None or sample["header"]["sport"] != sport:
        return [f"{kind} {path.name} has no sample match"]
    fails = []
    if kind == "pack":
        if (data.get("sport"), data.get("match_id")) != (sport, mid):
            fails.append(f"pack {path.name} names {data.get('sport')} {data.get('match_id')}")
        if not data.get("source"):
            fails.append(f"pack {path.name} names no source")
        if data.get("window", {}).get("to", "9") >= sample["header"]["date"]:
            fails.append(f"pack {path.name} reaches the match day")  # packs are the days before
    else:
        n, times = len(sample["moments"]), [m["video_t"] for m in data["moments"]]
        idxs = [m["idx"] for m in data["moments"]]
        if not data.get("youtube_id") or not data.get("source"):
            fails.append(f"video {path.name} lacks youtube_id or source")
        if any(not 0 <= i < n for i in idxs) or idxs != sorted(set(idxs)):
            fails.append(f"video {path.name} maps an idx outside 0..{n - 1} or out of order")
        if times != sorted(times):
            fails.append(f"video {path.name} runs backwards")
    return fails


def audit(data: Path = DATA) -> list[dict]:
    """One row per bundled match: its sport, id, source, moments, sha256 and failed checks."""
    rows, samples = [], {}
    for path in sorted((data / "sample").glob("*.json")):
        raw = path.read_bytes()
        sample = json.loads(raw)
        h = sample["header"]
        samples[h["match_id"]] = sample
        rows.append(
            {
                "sport": h["sport"],
                "match_id": h["match_id"],
                "source": SOURCE.get(h["sport"], "?"),
                "moments": len(sample["moments"]),
                "sha256": hashlib.sha256(raw).hexdigest()[:12],
                "checks": ["sample"],
                "fails": check_match(h, sample["moments"], path.name),
            }
        )
    by_id = {r["match_id"]: r for r in rows}

    def row(mid: str) -> dict:  # a file naming no sample gets a row of its own, to fail
        if mid not in by_id:
            by_id[mid] = {"sport": "?", "match_id": mid, "source": "?", "moments": 0}
            by_id[mid] |= {"sha256": "", "checks": [], "fails": ["no sample match"]}
            rows.append(by_id[mid])
        return by_id[mid]

    for kind, folder in (("pack", "packs"), ("video", "video")):
        for path in sorted((data / folder).glob("*.json")):
            r = row(path.stem.split("-", 1)[1])
            r["checks"].append(kind)
            r["fails"] += check_extra(kind, path, samples)
    for mid, peak in PEAKS.items():  # "Jump to the big moment" lands inside its match
        r = row(mid)
        r["checks"].append("peak")
        if not 0 <= peak < r["moments"]:
            r["fails"].append(f"peak {peak} is outside its {r['moments']} moments")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="one JSON list, for machines")
    args = ap.parse_args(argv)
    rows = audit()
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        cols = "sport match_id source moments sha256 checks result".split()
        table = [
            [
                r["sport"],
                r["match_id"],
                r["source"],
                str(r["moments"]),
                r["sha256"],
                "+".join(r["checks"]),
                "FAIL" if r["fails"] else "ok",
            ]
            for r in rows
        ]
        widths = [max(len(c), *(len(t[i]) for t in table)) for i, c in enumerate(cols)]
        for line in [cols, *table]:
            print("  ".join(v.ljust(w) for v, w in zip(line, widths, strict=True)).rstrip())
        for r in rows:
            for f in r["fails"]:
                print(f"FAIL {r['sport']} {r['match_id']}: {f}")
    return 1 if any(r["fails"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
