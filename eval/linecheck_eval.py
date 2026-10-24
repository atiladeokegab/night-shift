"""Line check next to the rules check on labelled lines (#298): precision and recall of a flag for
"wrong", with raw counts, on eval/checker_labels.jsonl and any labels file given (the held-out set,
once it's in). Both are scored on the same lines: the lead's moment lines, as Line check runs live
(a reply to the analyst is left out). Line check is called with recording off, so a labelled line
never trains the adapter. Tests never run it with a key.

    MUBIT_API_KEY=... uv run python -m eval.linecheck_eval [LABELS.jsonl ...]
    uv run python -m eval.linecheck_eval --dry     # FakeProvider: no network, nothing flagged
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent.linecheck import check
from data.matches import load_moments, match_header
from eval.checker_eval import LABELS, _pct, evaluate, load, report

WORKERS = 8


def model_flags(labels: list[dict], provider, workers: int = WORKERS) -> dict[str, list[str]]:
    """Line check's reasons per line_id ([] when it flags nothing); a failed call is "error"."""
    cache = {mid: (match_header(mid), load_moments(mid)) for mid in {x["match_id"] for x in labels}}

    def one(ln: dict) -> list[str]:
        header, moments = cache[ln["match_id"]]
        at = next(i for i, m in enumerate(moments) if m["idx"] == ln["moment_idx"])
        try:
            got = check(header, moments[at], moments[:at], ln["text"], provider)
        except Exception as exc:  # the key is never printed
            print(f"ERR {ln['line_id']} {type(exc).__name__}", file=sys.stderr)
            return ["error"]
        return [f"Checker model: {f} may be wrong" for f in got["wrong"]]

    with ThreadPoolExecutor(workers) as pool:
        return dict(zip((x["line_id"] for x in labels), pool.map(one, labels), strict=True))


def compare(labels: list[dict], provider) -> dict:
    """The rules check and Line check, each evaluated as eval/checker_eval.py scores a checker."""
    lead = [x for x in labels if not x.get("reply")]
    flags = model_flags(lead, provider)
    model = evaluate(
        lead, check=lambda ln, _cache: [r for r in flags[ln["line_id"]] if r != "error"]
    )
    return {
        "rules": evaluate(lead),
        "line_check": model,
        "errors": sum(["error"] == f for f in flags.values()),
    }


def table(name: str, out: dict) -> str:
    rows = [
        f"## {name}",
        "",
        "| | Lines | Wrong (labels) | Flagged | Caught | Missed | False alarms | Precision "
        "| Recall |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for label, key in (("Rules check", "rules"), ("Line check", "line_check")):
        s = out[key]["overall"]
        rows.append(
            f"| {label} | {s['lines']} | {s['tp'] + s['fn']} | {s['tp'] + s['fp']} | {s['tp']} | "
            f"{s['fn']} | {s['fp']} | {_pct(s['precision'])} | {_pct(s['recall'])} |"
        )
    rows += ["", f"Line check calls that failed (scored as no flag): {out['errors']}", ""]
    return "\n".join(rows)


def main(argv=None, env=os.environ) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.linecheck_eval", description=__doc__)
    p.add_argument("labels", nargs="*", type=Path, default=[LABELS], help="labelled lines (jsonl)")
    p.add_argument("--dry", action="store_true", help="FakeProvider: no network")
    p.add_argument(
        "--detail", action="store_true", help="also Line check's misses and false alarms"
    )
    a = p.parse_args(argv)
    from agent.commentator import FakeProvider, MubitProvider

    if a.dry:
        provider = FakeProvider()
    elif key := env.get("MUBIT_API_KEY"):
        provider = MubitProvider(key, record=False)  # a labelled line never trains the adapter
    else:
        print("needs MUBIT_API_KEY in the environment, or --dry", file=sys.stderr)
        return 2
    for path in a.labels:
        out = compare(load(path), provider)
        print(table(path.name, out))
        if a.detail:
            print(report(out["line_check"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
