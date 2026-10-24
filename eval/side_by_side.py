"""Big model vs ours, side by side, for the proof panel (#141). Held-out matches only.

    export MUBIT_API_KEY=...  # the owner's key, which records
    uv run python -m eval.side_by_side --adapters 6 --best 55.8

The app can't call the adapter: Mubit has no model ID for one ("you can't send a call to an adapter
by naming it as the model", docs.mubit.ai, Keep your model IDs), and its Try models console runs
only an adapter version that passed its tests. So this records the big model's line for each
moment, with recording off so a held-out moment never becomes a training example, and the adapter's
side says why it has no line. The adapter's result is copied from Mubit's console by hand, as
eval/record_adapter.py does. Writes data/side_by_side.json, which the page imports as recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent import feed
from agent.commentator import MODEL, MubitProvider
from core.stats import _cost
from eval.agreement import _line, held_out_matches
from scripts.replay_matches import pick

OUT = Path(__file__).resolve().parent.parent / "data" / "side_by_side.json"
WHY = (
    "Mubit serves an adapter only in its Try models console, and only once a version passes its "
    "tests; the app can't call it by API"
)
NO_LINE = "not compared: no adapter line"


def _moment(m: dict) -> str:
    who = next(iter(m.get("players", {}).values()), None)
    return " · ".join(str(p) for p in (m["type"], who, m.get("outcome")) if p)


def build(matches, provider, per_match: int, adapter: dict, today: str) -> dict:
    """matches: (header, moments) pairs, each held out and never a demo match."""
    pairs = []
    for header, moments in matches:
        key = (header["sport"], str(header["match_id"]))
        if not feed.held_out(*key) or key in feed.DEMO:
            raise ValueError(f"{key} is not a held-out match")
        at = {m["idx"]: i for i, m in enumerate(moments)}
        for idx in pick(moments, per_match):
            big = _line(header, moments, at[idx], provider)
            if big is None:
                continue
            m = moments[at[idx]]
            pairs.append(
                {
                    "sport": key[0],
                    "match_id": key[1],
                    "match": f"{header['home']} v {header['away']}, {header.get('date', '')[:4]}",
                    "moment_idx": idx,
                    "clock": m.get("clock"),
                    "moment": _moment(m),
                    "big": {
                        "text": big["text"],
                        "model": big["model"],
                        "first_word_ms": big["first_word_ms"],
                        "latency_ms": big["latency_ms"],
                        "cost_usd": _cost(big),
                    },
                    "adapter": None,
                    "verdict": NO_LINE,
                }
            )
    return {"recorded_on": today, "big_model": MODEL, "adapter": adapter, "pairs": pairs}


def main(argv=None, env=os.environ) -> dict:
    p = argparse.ArgumentParser(prog="python -m eval.side_by_side", description=__doc__)
    p.add_argument("--adapters", type=int, required=True, help="adapters Mubit's console lists")
    p.add_argument("--best", type=float, required=True, help="best adapter's match %%, console")
    p.add_argument("--status", default="not ready", help="the best adapter's status, console")
    p.add_argument("--name", help="the best adapter's name in the console")
    p.add_argument("--football", type=int, default=1, help="held-out football matches")
    p.add_argument("--cricket", type=int, default=1, help="held-out cricket matches")
    p.add_argument("--per-match", type=int, default=3, help="moments per match")
    a = p.parse_args(argv)
    if not env.get("MUBIT_API_KEY"):
        p.error("MUBIT_API_KEY is not set")
    adapter = {
        "name": a.name,
        "status": a.status,
        "adapters": a.adapters,
        "best_match_pct": a.best,
        "callable": False,
        "why": WHY,
    }
    big = MubitProvider(env["MUBIT_API_KEY"], record=False)
    today = datetime.now(UTC).date().isoformat()
    report = build(held_out_matches(a.football, a.cricket), big, a.per_match, adapter, today)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(report['pairs'])} pairs to {OUT}", file=sys.stderr)
    return report


if __name__ == "__main__":
    main()
