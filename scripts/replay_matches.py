"""Replay real matches through the commentator so the Mubit task trains on real, varied calls.

    export MUBIT_API_KEY=...  # the owner's key
    uv run python scripts/replay_matches.py --football 8 --cricket 8 --record

Each match is one Mubit session. Held-out and demo matches are never replayed, and neither is any
match already in the lines file. --fake runs offline with FakeProvider.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import feed  # noqa: E402
from agent.commentator import FakeProvider, MubitProvider, line_for, recorded  # noqa: E402
from core.insight import wrong_numbers  # noqa: E402

# Hand-picked StatsBomb competition-seasons, men's and women's, one match from each in turn.
FOOTBALL = [
    (43, 106),
    (72, 30),
    (55, 282),
    (37, 90),
    (2, 27),
    (53, 106),
    (9, 281),
    (49, 107),
    (1267, 107),
    (72, 107),
    (223, 282),
    (182, 281),
    (12, 27),
    (44, 107),
    (7, 235),
    (131, 281),
]
LINES = ROOT / "data" / "lines.jsonl"


def replayed(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    seen = set()
    for row in path.read_text(encoding="utf-8").splitlines():
        if row.strip():
            line = json.loads(row)
            seen.add((line["sport"], str(line["match_id"])))
    return seen


def eligible(sport: str, match_id: str, seen: set) -> bool:
    key = (sport, match_id)
    return key not in feed.DEMO and key not in seen and not feed.held_out(sport, match_id)


def football_candidates(seen: set):
    pools = []
    for comp, season in FOOTBALL:
        try:
            matches = feed.statsbomb_matches(comp, season)
        except Exception as exc:  # one missing competition must not stop the run
            print(f"skip football {comp}/{season}: {exc!r}", file=sys.stderr)
            continue
        ids = sorted(matches, key=lambda m: m["match_id"])
        pools.append([m for m in ids if eligible("football", str(m["match_id"]), seen)])
    while any(pools):
        for pool in pools:
            if pool:
                meta = pool.pop(0)
                yield str(meta["match_id"]), meta


def _world_cup(archive, ids: list[str], gender: str, seen: set):
    for match_id in ids:
        if not eligible("cricket", match_id, seen):
            continue
        match = json.loads(archive.read(f"{match_id}.json"))
        info = match.get("info") or {}
        event = info.get("event") if isinstance(info.get("event"), dict) else {}
        name = str(event.get("name", ""))
        if (
            info.get("gender") == gender
            and "T20 World Cup" in name
            and "Qualifier" not in name
            and len(match.get("innings") or []) >= 2
        ):
            yield match_id, frozenset(map(str, info.get("teams") or []))


def cricket_candidates(seen: set):
    """Newest T20 World Cup matches first, women's and men's in turn, each pair of teams once."""
    archive = feed.cricsheet_zip()
    ids = sorted((n[:-5] for n in archive.namelist() if n[:-5].isdigit()), key=int, reverse=True)
    pairs = set()
    for both in zip_longest(
        _world_cup(archive, ids, "female", seen), _world_cup(archive, ids, "male", seen)
    ):
        for match_id, pair in filter(None, both):
            if pair not in pairs:
                pairs.add(pair)
                yield match_id, None


def pick(moments: list[dict], k: int) -> list[int]:
    """Up to k moment indices: goals and wickets first (half at most), the rest spread evenly."""
    if len(moments) <= k:
        return [m["idx"] for m in moments]
    big = [
        m["idx"]
        for m in moments
        if m["outcome"] == "Goal" or m["type"] in ("Wicket", "Own Goal Against")
    ][: k // 2]
    others = [m["idx"] for m in moments if m["idx"] not in big]
    want = k - len(big)
    return sorted(big + [others[int(i * len(others) / want)] for i in range(want)])


def replay(
    sport: str, match_id: str, meta, provider, per_match: int, out: Path, trainer=None
) -> int:
    """`trainer`, a recording provider: a line that passes the number check is sent again."""
    header, moments = feed.load(sport, match_id, meta)
    written = failures = 0
    for idx in pick(moments, per_match):
        try:
            line = line_for(header, moments, idx, provider)
            if trainer and not wrong_numbers(line["text"], moments[idx], header, moments[:idx]):
                line["recorded"] = (recorded(header, moments, idx, provider=trainer) or {}).get(
                    "recorded", False
                )
        except Exception as exc:  # a failed call skips the moment, never the run
            failures += 1
            print(f"  {sport} {match_id} #{idx}: {exc!r}", file=sys.stderr)
            if failures >= 3:
                raise
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        written += 1
        print(f"  {sport} {match_id} #{idx} {line['latency_ms']}ms: {line['text']}")
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--football", type=int, default=0, help="football matches to replay")
    ap.add_argument("--cricket", type=int, default=0, help="cricket matches to replay")
    ap.add_argument("--per-match", type=int, default=10, help="moments called per match")
    ap.add_argument("--out", type=Path, default=LINES, help="JSON-lines file to append to")
    ap.add_argument("--fake", action="store_true", help="offline, with FakeProvider")
    # off by default: a line is recorded only once it passed the number check (#399)
    ap.add_argument("--record", action="store_true", help="send each checked line again, recorded")
    args = ap.parse_args(argv)

    if args.fake:
        provider = FakeProvider()
    else:
        key = os.environ.get("MUBIT_API_KEY")
        if not key:
            ap.error("MUBIT_API_KEY is not set (or pass --fake)")
        provider = MubitProvider(key, record=False)
    trainer = MubitProvider(key, record=True) if args.record and not args.fake else None

    seen = replayed(args.out)
    total = broken = 0
    for sport, wanted, candidates in (
        ("football", args.football, football_candidates),
        ("cricket", args.cricket, cricket_candidates),
    ):
        done = 0
        for match_id, meta in candidates(seen) if wanted else ():
            print(f"{sport} {match_id}")
            try:
                written = replay(sport, match_id, meta, provider, args.per_match, args.out, trainer)
            except Exception as exc:  # a bad match is skipped, not fatal
                print(f"skip {sport} {match_id}: {exc!r}", file=sys.stderr)
                broken += 1
                if broken >= 3:  # three matches in a row: the provider is down or the key is bad
                    return 1
                continue
            broken = 0
            seen.add((sport, match_id))
            total += written
            done += written > 0
            if done >= wanted:
                break
        print(f"{sport}: {done} matches")
    print(f"{total} lines -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
