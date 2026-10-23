"""Record the adapter's result, from Mubit's Try models run by hand, so /stats and the proof panel
show it. Writes to the store the server uses: STORE_DIR locally, or MODE=cloud STORE_URL=gs://...

    uv run python -m eval.record_adapter --status ready --kept 31 --agree 23 --total 25

On a deployed service, write a fresh local store and copy it over the service's object (here
staging; production is .../night-shift). The copy replaces earlier adapter records, which is fine:
the panel reads only the latest, and the server never writes this kind. /stats reads it next call.

    d=$(mktemp -d)
    STORE_DIR=$d uv run python -m eval.record_adapter --status ready --kept 31 --agree 23 --total 25
    gcloud storage cp $d/adapter.jsonl \
        gs://hackathon-starter-ao-state/night-shift-staging/adapter.jsonl
"""

import argparse
import os
import sys
from datetime import UTC, datetime

from core.store import open_store


def main(argv=None, env=os.environ) -> dict:
    p = argparse.ArgumentParser(prog="python -m eval.record_adapter", description=__doc__)
    p.add_argument("--status", required=True, choices=["not_trained", "training", "ready"])
    p.add_argument("--kept", type=int, help="kept examples Mubit's console shows for the task")
    p.add_argument("--agree", type=int, help="moments where the adapter agreed with the big model")
    p.add_argument("--total", type=int, help="held-out moments compared")
    a = p.parse_args(argv)
    if (a.agree is None) != (a.total is None):
        p.error("--agree and --total go together")
    if a.kept is not None and a.kept < 0:
        p.error("--kept can't be negative")
    if a.total is not None and not 0 <= a.agree <= a.total:
        p.error("need 0 <= --agree <= --total")
    record = {
        "status": a.status,
        "kept": a.kept,
        "agree": a.agree,
        "total": a.total,
        "created_at": datetime.now(UTC).isoformat(),
    }
    open_store(env).append("adapter", record)
    print(f"recorded adapter: {record}", file=sys.stderr)
    return record


if __name__ == "__main__":
    main()
