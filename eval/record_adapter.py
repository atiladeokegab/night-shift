"""Record a Mubit task's adapter result, read off Mubit's console by hand, so /stats and the proof
panel show it. Writes to the store the server uses: STORE_DIR locally, or MODE=cloud STORE_URL=gs://...

    uv run python -m eval.record_adapter --status ready --kept 31 --agree 23 --total 25
    uv run python -m eval.record_adapter --task line_check --status ready \
        --version 1 --score 82 --passed

--task defaults to commentary. Each task keeps its own records; /stats shows each task's latest.

On a deployed service, copy the service's adapter records down, append, and copy them back
(here staging; production is .../night-shift), so one task's record doesn't replace the others'.
The server never writes this kind. /stats reads it next call.

    d=$(mktemp -d) o=gs://hackathon-starter-ao-state/night-shift-staging/adapter.jsonl
    gcloud storage cp $o $d/adapter.jsonl
    STORE_DIR=$d uv run python -m eval.record_adapter --task line_check --status ready --version 1
    gcloud storage cp $d/adapter.jsonl $o
"""

import argparse
import os
import sys
from datetime import UTC, datetime

from core.store import open_store

# the Mubit tasks: the lead's commentary (prompt.md), "Where are we?" (#194), the Line check (#209)
TASKS = ["commentary", "where_are_we", "line_check"]


def main(argv=None, env=os.environ) -> dict:
    p = argparse.ArgumentParser(prog="python -m eval.record_adapter", description=__doc__)
    p.add_argument("--task", default="commentary", choices=TASKS)
    p.add_argument("--status", required=True, choices=["not_trained", "training", "ready"])
    p.add_argument("--kept", type=int, help="kept examples Mubit's console shows for the task")
    p.add_argument("--agree", type=int, help="moments where the adapter agreed with the big model")
    p.add_argument("--total", type=int, help="held-out moments compared")
    p.add_argument("--version", type=int, help="the adapter version Mubit's console shows")
    p.add_argument("--score", type=float, help="its test score in Mubit's console, 0 to 100")
    gate = p.add_mutually_exclusive_group()
    gate.add_argument("--passed", action="store_true", default=None, help="Mubit marks it Passed")
    gate.add_argument("--failed", dest="passed", action="store_false", help="Mubit marks it Failed")
    a = p.parse_args(argv)
    if (a.agree is None) != (a.total is None):
        p.error("--agree and --total go together")
    if a.kept is not None and a.kept < 0:
        p.error("--kept can't be negative")
    if a.total is not None and not 0 <= a.agree <= a.total:
        p.error("need 0 <= --agree <= --total")
    if a.version is not None and a.version < 1:
        p.error("--version starts at 1")
    if a.score is not None and not 0 <= a.score <= 100:
        p.error("need 0 <= --score <= 100")
    record = {
        "task": a.task,
        "status": a.status,
        "kept": a.kept,
        "agree": a.agree,
        "total": a.total,
        "version": a.version,
        "score": a.score,
        "passed": a.passed,
        "created_at": datetime.now(UTC).isoformat(),
    }
    open_store(env).append("adapter", record)
    print(f"recorded adapter: {record}", file=sys.stderr)
    return record


if __name__ == "__main__":
    main()
