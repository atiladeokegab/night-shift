"""How well does the number and event check work? Precision and recall on labelled lines (#219).

    uv run python -m eval.checker_eval                  # score today's checker on the labels
    uv run python -m eval.checker_eval sample LINES     # draw the sample from a copy of lines.jsonl
    uv run python -m eval.checker_eval heldout LINES    # draw the held-out sample (#293)
    uv run python -m eval.checker_eval --heldout        # score the checker on the held-out labels

The labels (eval/checker_labels.jsonl) were made before the checker was run on them, by a separate
agent reading each line against its moment's data, the match header and the moments before it; the
rules it followed are RULES below. They are a model's labels, not a human's.

The checker is scored exactly as the replay runs it (core/insight.py `checked`): `wrong_numbers`,
which includes `wrong_event`, with the header and the moments before the line; a reply to the
analyst is checked over the Stat moment it was said over (`said_over`), as its fix is. A flag
is "wrong"; precision is the share of flagged lines labelled wrong, recall the share of wrong
lines flagged.

The labels count only what a line says that is false, never what it leaves out, so the headline
leaves out the checker's omission reasons (OMISSIONS); the as-live line counts every reason.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

from core import insight
from data.matches import SAMPLE, load_moments, match_header

LABELS = Path(__file__).with_name("checker_labels.jsonl")
SIZE, FLOOR, SEED = 300, 30, 219
# drawn after the checker was tuned on LABELS' misses: a different seed, none of LABELS' lines, and
# the analyst's lines too (#293)
HELDOUT, HELDOUT_SEED = Path(__file__).with_name("heldout_labels.jsonl"), 293
OMISSIONS = ("the milestone is unsaid", "the line never says how the shot ended")

RULES = """\
Label each line "right" or "wrong" by reading it against the match header, its moment's data and the
moments before it (for a reply, also what the analyst just said).
1. Wrong if it states a number (score, minute, clock, points, runs, wickets, overs, balls, lap,
   position, gap, count) that the data contradicts or does not give. A count from recent play in
   the moments before ("three sixes in four balls") is given. A number the analyst just said is
   given to a reply.
2. Wrong if it names the wrong player, driver or team for the play, or says a team leads, trails or
   is level when the score says otherwise.
3. Wrong if it calls an event the moment is not (a goal for a saved shot, a save for a shot off
   target, a penalty for a booking, a make for a miss, a wicket for a boundary).
4. Wrong if it leaks the model's reasoning instead of commentating ("wait, let me reconsider",
   "the event parameter says").
5. Right otherwise. Leaving something out is never wrong. Colour, emotion and hedged opinion are not
   facts. Number words count as numbers ("fifty-eight" is 58).
"""


def bundled() -> dict[str, dict]:
    """Every sample's header, hidden ones too: the held-out set was drawn from all of them."""
    ids = [p.stem.split("-", 1)[1] for p in sorted(SAMPLE.glob("*.json"))]
    return {mid: match_header(mid) for mid in ids}


def sample(
    lines_path: Path,
    size: int = SIZE,
    seed: int = SEED,
    analyst: bool = False,
    skip: frozenset = frozenset(),
) -> list[dict]:
    """Distinct lead lines (match, moment, text) with their moment in a bundled match, stratified
    by match: each gets FLOOR lines (or all it has) when the budget allows, the rest go by each
    match's share. `analyst` keeps the analyst's lines too; `skip` leaves out these
    (match, moment, text)."""
    if size < 0:
        raise ValueError("sample size must be non-negative")
    matches = bundled()
    moments = {mid: {m["idx"] for m in load_moments(mid)} for mid in matches}
    seen, pool = set(skip), {mid: [] for mid in matches}
    for raw in lines_path.read_text().splitlines():
        ln = json.loads(raw)
        mid, idx, text = ln.get("match_id"), ln.get("moment_idx"), (ln.get("text") or "").strip()
        if (ln.get("speaker") == "analyst" and not analyst) or ln.get("fallback") or not text:
            continue  # a fallback is built from the data, so it is right by construction
        if mid not in matches or idx not in moments[mid] or (mid, idx, text) in seen:
            continue
        seen.add((mid, idx, text))
        keep = {"line_id": ln["line_id"], "match_id": mid, "moment_idx": idx, "text": text}
        said_as = {k: ln[k] for k in ("reply", "insight", "open") if ln.get(k)}
        pool[mid].append(
            {
                **keep,
                **({"speaker": ln["speaker"]} if analyst and ln.get("speaker") else {}),
                **said_as,
            }
        )
    target = min(size, sum(map(len, pool.values())))
    floors = {mid: min(len(p), FLOOR) for mid, p in pool.items()}
    if sum(floors.values()) > target:
        take = dict.fromkeys(pool, 0)
        rest = floors
    else:
        take = floors
        rest = {mid: len(p) - take[mid] for mid, p in pool.items()}
    left = target - sum(take.values())
    denominator = sum(rest.values())
    share = {mid: left * n / denominator if denominator else 0 for mid, n in rest.items()}
    for mid in sorted(share, key=lambda k: share[k] - int(share[k]), reverse=True):
        take[mid] += int(share[mid])  # whole shares first, then the largest remainders
    for mid in sorted(share, key=lambda k: share[k] - int(share[k]), reverse=True):
        if sum(take.values()) < target and take[mid] < len(pool[mid]):
            take[mid] += 1
    rng = random.Random(seed)
    return [ln for mid in sorted(pool) for ln in rng.sample(pool[mid], take[mid])]


def context(line: dict, before: int = 8) -> dict:
    """What the labeller reads: the header, the moment, the moments just before it, and for a
    reply what the analyst just said. The same data the commentator had."""
    moments = load_moments(line["match_id"])
    at = next(i for i, m in enumerate(moments) if m["idx"] == line["moment_idx"])
    out = {
        "header": match_header(line["match_id"]),
        "moment": moments[at],
        "moments_before": moments[max(0, at - before) : at],
    }
    if line.get("reply"):
        out["analyst_just_said"] = line["reply"]["heard"]
    if line.get("insight"):  # an analyst line: the stat it was given to say
        out["analyst_was_given"] = line["insight"]["detail"]
    return out


def verdict(line: dict, cache: dict | None = None) -> list[str]:
    """Today's checker on a stored line, as the replay ran it; [] when it passes."""
    cache = {} if cache is None else cache
    mid = line["match_id"]
    if mid not in cache:
        cache[mid] = match_header(mid), load_moments(mid)
    header, moments = cache[mid]
    over = insight.said_over(line, lambda _: moments)
    if over:
        m, past = over[-1], over[:-1]
    else:
        at = next(i for i, x in enumerate(moments) if x["idx"] == line["moment_idx"])
        m, past = moments[at], moments[:at]
    return insight.wrong_numbers(line["text"], m, header, past)


def factual(reasons: list[str]) -> list[str]:
    return [r for r in reasons if not r.startswith(OMISSIONS)]


def score(rows: list[tuple[bool, bool]]) -> dict:
    """rows: (labelled wrong, flagged). Precision and recall of a flag for "wrong"."""
    c = Counter(rows)
    tp, fp, fn, tn = c[True, True], c[False, True], c[True, False], c[False, False]
    return {
        "lines": len(rows),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def evaluate(labels: list[dict], check=verdict) -> dict:
    """The scores overall and per sport, and every miss and false alarm with its reasons."""
    matches, cache, results = bundled(), {}, []
    for ln in labels:
        reasons = check(ln, cache)
        sport = matches[ln["match_id"]]["sport"]
        flagged = bool(factual(reasons))
        results.append({**ln, "sport": sport, "reasons": reasons, "flagged": flagged})
    wrong = [r["label"] == "wrong" for r in results]
    out = {
        "overall": score([(w, r["flagged"]) for w, r in zip(wrong, results, strict=True)]),
        "as_live": score([(w, bool(r["reasons"])) for w, r in zip(wrong, results, strict=True)]),
        "by_sport": {
            s: score([(r["label"] == "wrong", r["flagged"]) for r in results if r["sport"] == s])
            for s in sorted({r["sport"] for r in results})
        },
        "misses": [r for r in results if r["label"] == "wrong" and not r["flagged"]],
        "false_alarms": [r for r in results if r["label"] == "right" and r["flagged"]],
    }
    return out


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def report(out: dict) -> str:
    rows = [("overall", out["overall"]), *out["by_sport"].items()]
    lines = [
        "| | Lines | Wrong (labels) | Flagged | Caught | Missed | False alarms | Precision "
        "| Recall |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in rows:
        lines.append(
            f"| {name} | {s['lines']} | {s['tp'] + s['fn']} | {s['tp'] + s['fp']} | {s['tp']} | "
            f"{s['fn']} | {s['fp']} | {_pct(s['precision'])} | {_pct(s['recall'])} |"
        )
    live = out["as_live"]
    lines += [
        "",
        f"As live (omission reasons count as flags): precision {_pct(live['precision'])}, "
        f"recall {_pct(live['recall'])}, {live['fp']} false alarms.",
        "",
        f"Misses ({len(out['misses'])}): labelled wrong, not flagged",
    ]
    for r in out["misses"]:
        lines.append(f"- [{r['sport']} {r['match_id']} #{r['moment_idx']}] {r['text']}")
        lines.append(f"  label: {r.get('why', '')}")
    lines += ["", f"False alarms ({len(out['false_alarms'])}): labelled right, flagged"]
    for r in out["false_alarms"]:
        lines.append(f"- [{r['sport']} {r['match_id']} #{r['moment_idx']}] {r['text']}")
        lines.append(f"  check: {'; '.join(factual(r['reasons']))}")
    return "\n".join(lines)


def load(path: Path = LABELS) -> list[dict]:
    return [json.loads(raw) for raw in path.read_text().splitlines() if raw.strip()]


def labelled() -> frozenset:
    """The (match, moment, text) of every line in LABELS, which the held-out sample leaves out."""
    return frozenset((ln["match_id"], ln["moment_idx"], ln["text"]) for ln in load())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", default="score", choices=["score", "sample", "heldout"])
    ap.add_argument("lines", nargs="?", type=Path, help="sample: a copy of the store's lines.jsonl")
    ap.add_argument("--json", action="store_true", help="score: the full result as JSON")
    ap.add_argument("--heldout", action="store_true", help="score: the held-out labels")
    args = ap.parse_args(argv)
    if args.cmd in ("sample", "heldout"):
        if not args.lines:
            ap.error(f"{args.cmd} needs a lines.jsonl")
        drawn = (
            sample(args.lines)
            if args.cmd == "sample"
            else sample(args.lines, seed=HELDOUT_SEED, analyst=True, skip=labelled())
        )
        for ln in drawn:
            print(json.dumps({**ln, "context": context(ln)}))
        return 0
    out = evaluate(load(HELDOUT if args.heldout else LABELS))
    print(json.dumps(out, indent=1) if args.json else report(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
