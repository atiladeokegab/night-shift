"""Score check before/after a Mubit version change: one fixed request, sent the way live sends it
(agent/commentator.default_provider -> MubitProvider, agent/scorecheck.build_request).

The line is a stored live line for Cahill's goal, Chelsea-Spurs moment 26 (1-2), that says
"Tottenham still lead one-nil": the key (eval/linecheck.py `gold`) is `wrong`. Run it once before
a Score check version is set to serve and once after; the two files show the same request
answered by whatever Mubit then serves.

    export MUBIT_API_KEY=... MUBIT_RECORD=off PYTHONPATH=.
    uv run python scripts/scorecheck_before_after.py before    # then: after

Writes eval/scorecheck_before_after_<UTC time>_<label>.json and prints the same."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent import scorecheck
from agent.commentator import FakeProvider, default_provider
from data.matches import load_moments, match_header

MATCH, IDX = "3754092", 26
LINE = (
    "Gary Cahill! Chelsea pull one back with a half volley, "
    "but Tottenham still lead one-nil in this second half!"
)
KEY = "wrong"  # the score said is 1-0; Chelsea 1, Tottenham 2


def run(label: str) -> dict:
    provider = default_provider()
    if isinstance(provider, FakeProvider):
        sys.exit("no MUBIT_API_KEY: nothing to ask Mubit")
    header, moments = match_header(MATCH), load_moments(MATCH)
    m = next(m for m in moments if m["idx"] == IDX)
    request = scorecheck.build_request(header, m, LINE)
    reply = provider.call(request)
    said = "".join(b.get("text", "") for b in reply["content"] if b["type"] == "text")
    return {
        "label": label,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "match_id": MATCH,
        "idx": IDX,
        "line": LINE,
        "key": KEY,
        "answer": said,
        "label_parsed": scorecheck.parse(said),
        "matches_key": scorecheck.parse(said) == KEY,
        "mubit_request_id": reply.get("request_id"),
        "served_by": reply.get("served_by"),  # the model or version Mubit's reply names
        "middleware": reply.get("middleware"),  # every x-middleware-* header Mubit sent back
        "record": provider.record,
    }


if __name__ == "__main__":
    out = run(sys.argv[1] if len(sys.argv) > 1 else "before")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = (
        Path(__file__).resolve().parent.parent
        / "eval"
        / f"scorecheck_before_after_{stamp}_{out['label']}.json"
    )
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print(f"saved {path}")
