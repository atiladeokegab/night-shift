"""A producer's fix on one line, then the next lines on that match carry it: the end-to-end
moment on the live site, with its evidence.

1. Replay A from moment --idx: the line said there, and the lines after it, before any fix.
2. POST /lines/{id}/fix on that line (PRODUCER_TOKEN from the environment, never printed).
3. Replay B from moment --idx + 1: every later line's request carries the fix (with_fixes reads the
   match's fixes on each call). Prints the fix block those requests carry, then each later moment's
   line before and after, with B's Mubit request ids to find the request in Mubit's console.

Two partial replays, both `smoke` so the cost per full replay doesn't move. A replay served from
stored lines (over a cap) makes no new line: the script stops and says so.

    PRODUCER_TOKEN=... uv run python scripts/fix_then_later.py [URL]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.commentator import FIXES, _fixes  # noqa: E402

URL = "https://night-shift-5zvig7nbvq-ew.a.run.app"
MATCH = "3913122"  # Brighton v Bristol City (WSL, 2024)
# Terland's opener, 1-0: the fix names Brighton "the Seagulls", which later lines can follow
IDX = 8
TEXT = "Elisabeth Terland scores! The Seagulls lead one-nil."
REASON = "Call Brighton the Seagulls"


def replay(client: httpx.Client, match: str, start: int) -> list[dict]:
    """The lead's new lines of a replay from moment `start`, in order: history lines and the
    analyst's are left out."""
    body = {"match_id": match, "speed": 1e6, "smoke": True, "start_idx": start}
    rid = client.post("/replays", json=body).raise_for_status().json()["replay_id"]
    lines, name = [], None
    with client.stream("GET", f"/replays/{rid}/stream", timeout=600) as resp:
        resp.raise_for_status()
        for row in resp.iter_lines():
            if row.startswith("event: "):
                name = row.removeprefix("event: ")
            elif row.startswith("data: ") and name in ("line", "error"):
                data = json.loads(row.removeprefix("data: "))
                if name == "error":
                    raise SystemExit(f"replay {rid} stopped: {data}")
                if data.get("history") or data.get("speaker", "lead") != "lead" or "reply" in data:
                    continue
                if data.get("cached"):
                    raise SystemExit(f"replay {rid} played stored lines (over a cap): no new line")
                lines.append(data)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", nargs="?", default=URL)
    ap.add_argument("--match", default=MATCH)
    ap.add_argument("--idx", type=int, default=IDX, help="the moment whose line is fixed")
    ap.add_argument("--text", default=TEXT, help="the producer's line")
    ap.add_argument("--reason", default=REASON)
    a = ap.parse_args()
    token = os.environ.get("PRODUCER_TOKEN", "")
    moments = json.loads((Path("data/sample") / f"football-{a.match}.json").read_text())["moments"]

    with httpx.Client(base_url=a.url, timeout=60) as client:
        before = {ln["moment_idx"]: ln for ln in replay(client, a.match, a.idx)}
        line = before.get(a.idx)
        if not line:
            raise SystemExit(f"replay A said no line at moment {a.idx}")
        print(f"Moment {a.idx}, said: {line['text']}")
        print(f"  line {line['line_id']}")

        r = client.post(
            f"/lines/{line['line_id']}/fix",
            json={"corrected_text": a.text, "reason": a.reason},
            headers={"X-Producer-Token": token},
        )
        if r.status_code != 200:
            raise SystemExit(f"fix refused: {r.status_code} {r.text[:300]}")
        fix = r.json()
        print(f"Producer's fix: {a.text}")
        print(f"  correction request {fix.get('mubit_request_id')}, recorded {fix.get('recorded')}")

        after = replay(client, a.match, a.idx + 1)

    block = _fixes(
        [m for m in moments if m["idx"] <= a.idx],
        [{"moment_idx": a.idx, "said": fix["said"], "reason": a.reason, "fixed": a.text}],
    )
    print("\nEvery later request on this match carries, in its user message:")
    print("  " + FIXES.format(fixes=block).replace("\n", "\n  "))
    clock = {m["idx"]: m["clock"] for m in moments}
    print("\nThe next lines on this match carry the producer's fix:")
    for ln in after:
        old = before.get(ln["moment_idx"], {}).get("text", "(no line)")
        mark = "  CHANGED" if old != ln["text"] else ""
        print(f"\nMoment {ln['moment_idx']} ({clock.get(ln['moment_idx'], '')}){mark}")
        print(f"  before the fix: {old}")
        print(f"  after the fix:  {ln['text']}")
        print(f"  requests: {', '.join(ln.get('mubit_request_ids') or []) or 'none'}")


if __name__ == "__main__":
    main()
