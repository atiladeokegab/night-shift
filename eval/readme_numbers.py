"""The README's check table, generated from eval/checker_eval.py's output so it can't drift.

    uv run python -m eval.readme_numbers           # print the block
    uv run python -m eval.readme_numbers --write   # rewrite it in README.md, between the markers

The rules rows are today's checker on the committed labels. The Line check row is the keyed run
/stats serves (eval/linecheck_heldout.json): it needs a key, so it is read, never rerun.
tests/test_readme_numbers.py fails when README.md's block differs from this output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval import checker_eval

README = Path(__file__).resolve().parent.parent / "README.md"
LINECHECK = Path(__file__).with_name("linecheck_heldout.json")
START, END = "<!-- checker-eval:start -->", "<!-- checker-eval:end -->"


def lead(labels: list[dict]) -> list[dict]:
    """The lead's moment lines, as Line check runs live (eval/linecheck_eval.py `compare`)."""
    return [ln for ln in labels if not ln.get("reply")]


def counts(s: dict) -> dict:
    return {"lines": s["lines"], "wrong": s["tp"] + s["fn"], "caught": s["tp"], "fa": s["fp"]}


def rows() -> list[tuple[str, str, dict]]:
    held = checker_eval.load(checker_eval.HELDOUT)
    first = checker_eval.load(checker_eval.LABELS)
    lc = json.loads(LINECHECK.read_text())
    return [
        (
            "Held-out, every line",
            "Number check (rules)",
            counts(checker_eval.evaluate(held)["overall"]),
        ),
        (
            "Held-out, lead lines",
            "Number check (rules)",
            counts(checker_eval.evaluate(lead(held))["overall"]),
        ),
        (
            "Held-out, lead lines",
            "Line check (keyed run)",
            {
                "lines": lc["lines"],
                "wrong": lc["wrong"],
                "caught": lc["line_check"]["caught"],
                "fa": lc["line_check"]["false_alarms"],
            },
        ),
        (
            "First set (rules tuned on it)",
            "Number check (rules)",
            counts(checker_eval.evaluate(first)["overall"]),
        ),
    ]


def block() -> str:
    out = [
        START,
        "| Set | Checker | Lines | Wrong (labels) | Caught | False alarms |",
        "|---|---|---|---|---|---|",
    ]
    for name, checker, c in rows():
        caught = f"{c['caught']} of {c['wrong']}"
        out.append(f"| {name} | {checker} | {c['lines']} | {c['wrong']} | {caught} | {c['fa']} |")
    out.append(END)
    return "\n".join(out)


def written(text: str) -> str:
    """README.md's text with the block between the markers replaced by today's."""
    head, rest = text.split(START, 1)
    return head + block() + rest.split(END, 1)[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="rewrite the block in README.md")
    args = ap.parse_args(argv)
    if args.write:
        README.write_text(written(README.read_text()))
    else:
        print(block())
    return 0


if __name__ == "__main__":
    sys.exit(main())
