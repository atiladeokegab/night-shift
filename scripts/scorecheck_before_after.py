"""Score check before/after a Mubit version change: one fixed request, sent the way live sends it
(agent/commentator.default_provider -> MubitProvider, agent/scorecheck.build_request).

The line is a stored live line for Cahill's goal, Chelsea-Spurs moment 26 (1-2), that says
"Tottenham still lead one-nil": the key (eval/linecheck.py `gold`) is `wrong`. Run it once before
a Score check version is set to serve and once after; the two files show the same request
answered by whatever Mubit then serves.

    export MUBIT_API_KEY=... MUBIT_RECORD=off PYTHONPATH=.
    uv run python scripts/scorecheck_before_after.py before [--case NAME | --line-id ID]
    (then the same with `after`)

Cases: `cahill` (default), and two lines the base model's Score check answered against the key on
live (the /ledger rows kind "corrected": Claude's first reply differed from the key): `jordan`,
`kohli`. `--line-id` takes a stored line (GET /lines/<id>, no key needed) from a supported sport
with a canonical Score check label, computed from the event data (eval/linecheck.py `gold`).

Writes eval/scorecheck_before_after_<UTC time>_<label>_<case>.json and prints the same."""

import argparse
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from agent import scorecheck
from agent.commentator import FakeProvider, default_provider
from data.matches import load_moments, match_header
from eval.linecheck import gold

SITE = "https://night-shift-5zvig7nbvq-ew.a.run.app"
CASES = {  # name: (match, idx, line)
    "cahill": (
        "3754092",
        26,
        "Gary Cahill! Chelsea pull one back with a half volley, "
        "but Tottenham still lead one-nil in this second half!",
    ),
    "jordan": (
        "0049700088",
        30,
        "Jordan with the driving layup! Chicago Bulls take the lead, 85-86!",
    ),
    "kohli": (
        "1298150",
        53,
        "Kohli takes three byes on the free hit! India need just two from the final ball!",
    ),
}


def pick(case: str, line_id: str | None) -> tuple[str, int, str]:
    if not line_id:
        return CASES[case]
    with urllib.request.urlopen(f"{SITE}/lines/{line_id}", timeout=20) as r:
        ln = json.load(r)
    return ln["match_id"], ln["moment_idx"], ln.get("tried") or ln["text"]


def run(label: str, case: str, line_id: str | None = None) -> dict:
    match, idx, line = pick(case, line_id)
    header, moments = match_header(match), load_moments(match)
    i = next(i for i, m in enumerate(moments) if m["idx"] == idx)
    moment = moments[i]
    if moment["sport"] not in scorecheck.SPORTS:
        raise SystemExit(f"Score check does not support {moment['sport']}")
    labels = gold(header, moment, moments[:i], line)
    key = labels.get("score") if labels else None
    if key not in scorecheck.LABELS:
        raise SystemExit("line has no canonical score label")
    provider = default_provider()
    if isinstance(provider, FakeProvider):
        raise SystemExit("no MUBIT_API_KEY: nothing to ask Mubit")
    reply = provider.call(scorecheck.build_request(header, moment, line))
    said = "".join(b.get("text", "") for b in reply["content"] if b["type"] == "text")
    return {
        "label": label,
        "case": line_id or case,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "match_id": match,
        "idx": idx,
        "line": line,
        "key": key,
        "answer": said,
        "label_parsed": scorecheck.parse(said),
        "matches_key": scorecheck.parse(said) == key,
        "mubit_request_id": reply.get("request_id"),
        "served_by": reply.get("served_by"),  # the model or version Mubit's reply names
        "middleware": reply.get("middleware"),  # every x-middleware-* header Mubit sent back
        "record": provider.record,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="?", default="before")
    ap.add_argument("--case", choices=CASES, default="cahill")
    ap.add_argument("--line-id")
    a = ap.parse_args()
    out = run(a.label, a.case, a.line_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"scorecheck_before_after_{stamp}_{a.label}_{a.line_id or a.case}.json"
    path = Path(__file__).resolve().parent.parent / "eval" / name
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print(f"saved {path}")
