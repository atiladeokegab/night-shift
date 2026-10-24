"""Seed the Line check task (#209) on Mubit: each stored moment line, with its moment's facts, and
the label code gives it (eval/linecheck.py). Lines of the held-out matches (3913122, 9636) never go.

    uv run python -m eval.seed_linecheck --dry                    # FakeProvider, no network
    MODE=cloud STORE_URL=gs://hackathon-starter-ao-state/night-shift \\
        uv run python -m eval.seed_linecheck --go 200             # recorded calls; MUBIT_API_KEY
    uv run python -m eval.seed_linecheck --pilot 50   # unkept: agrees with gold, and on a repeat?
    uv run python -m eval.seed_linecheck --held-out > held_out.jsonl   # the unseen test set
    uv run python -m eval.seed_linecheck --score outputs.jsonl    # {"id", "output"} per line

`--lines FILE` reads a copy of lines.jsonl instead of the store. A planted example is a right
line with one field changed so it is wrong (`planted: true`); it is never a real error.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.commentator import CORRECTION, FakeProvider, MubitProvider
from core.store import open_store
from data.matches import load_moments, match_header
from eval.linecheck import FIELDS, HELD_OUT, build_request, dumps, example_id, gold, parse, plant

SEED = 209
WORKERS = 8  # calls in flight on --go and --pilot


def examples(lines: list[dict]) -> list[dict]:
    """Every distinct moment line code can label, and one planted error per line where it can."""
    rng, out, seen, cache = random.Random(SEED), [], set(), {}
    for line in lines:
        key = (line.get("match_id"), line.get("moment_idx"), line.get("text"))
        # an analyst's or a reply's line is said over a Stat, and a fallback is the data itself
        if key in seen or not line.get("text") or line.get("insight") or line.get("reply"):
            continue
        if line.get("fallback"):
            continue
        seen.add(key)
        mid = line["match_id"]
        if mid not in cache:
            try:
                cache[mid] = match_header(mid), load_moments(mid)
            except KeyError:  # not a bundled match: no facts to check against
                cache[mid] = None
        if cache[mid] is None:
            continue
        header, moments = cache[mid]
        i = next((i for i, m in enumerate(moments) if m["idx"] == line["moment_idx"]), None)
        if i is None:
            continue
        m, past, text = moments[i], moments[:i], line["text"]
        label = gold(header, m, past, text)
        if label is None:
            continue
        base = {"match_id": mid, "sport": m["sport"], "idx": m["idx"], "held_out": mid in HELD_OUT}
        out.append({**base, "id": example_id(mid, m["idx"], text), "text": text, "gold": label})
        fields = [f for f in FIELDS if label[f] == "ok"]
        rng.shuffle(fields)
        for f in fields:
            planted = plant(header, m, past, text, label, f)
            if planted:
                pid = example_id(mid, m["idx"], planted)
                gold_p = {**label, f: "wrong"}
                out.append({**base, "id": pid, "text": planted, "gold": gold_p, "planted": True})
                break
    return out


def request(ex: dict) -> dict:
    header, moments = match_header(ex["match_id"]), load_moments(ex["match_id"])
    i = next(i for i, m in enumerate(moments) if m["idx"] == ex["idx"])
    return build_request(header, moments[i], moments[:i], ex["text"])


def batch(exs: list[dict], n: int) -> list[dict]:
    """The first n training examples in a fixed shuffle; a held-out match's line never."""
    train = [e for e in exs if not e["held_out"] and e["match_id"] not in HELD_OUT]
    random.Random(SEED).shuffle(train)
    return train[:n]


def _text(reply: dict) -> str:
    return "".join(b.get("text", "") for b in reply["content"] if b["type"] == "text").strip()


def _go_one(ex: dict, provider) -> tuple[str, str]:
    req, want = request(ex), dumps(ex["gold"])
    try:
        said = _text(provider.call(req))
        matched = said == want
        corrected = "-"
        if not matched:
            req["messages"] += [
                {"role": "assistant", "content": said or "(no reply)"},
                {"role": "user", "content": CORRECTION.format(text=want)},
            ]
            corrected = _text(provider.call(req)) == want
    except Exception as exc:  # one failed call never stops the batch; the key is never printed
        return "error", f"ERR {ex['id']} {type(exc).__name__}"
    kind = "matched" if matched else "corrected" if corrected else "uncorrected"
    return kind, f"REC {ex['id']} matched={matched} corrected={corrected}"


def go(exs: list[dict], provider, workers: int = WORKERS) -> Counter:
    """One recorded call per example, `workers` in flight; a reply that isn't the gold gets the
    correction as the next turn of that call, with the exact gold JSON, as a producer's fix does
    (agent/commentator.py)."""
    tally = Counter()
    with ThreadPoolExecutor(workers) as pool:
        for kind, line in pool.map(lambda ex: _go_one(ex, provider), exs):
            print(line, flush=True)
            tally[kind] += 1
    return tally


def _pilot_one(ex: dict, provider) -> tuple[dict | None, bool, str]:
    first = _text(provider.call(request(ex)))
    again = _text(provider.call(request(ex)))
    return parse(first), first == again, first


def pilot(exs: list[dict], provider, workers: int = WORKERS) -> Counter:
    """Two unkept calls per example: does Claude give the gold, and the same answer again?"""
    tally = Counter()
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(_pilot_one, ex, provider): ex for ex in exs}
        for fut in as_completed(futures):
            ex = futures[fut]
            try:
                got, same, said = fut.result()
            except Exception as exc:  # the key is never printed
                print(f"ERR {ex['id']} {type(exc).__name__}", flush=True)
                tally["error"] += 1
                continue
            tally["n"] += 1
            agree = got == ex["gold"]
            tally["agree"] += agree
            tally.update(f for f in FIELDS if got and got[f] == ex["gold"][f])
            tally["same"] += same
            if not (agree and same):
                print(
                    f"PILOT {ex['id']} agree={agree} same={same} gold={dumps(ex['gold'])}"
                    f" reply={said!r} line={ex['text']!r}",
                    flush=True,
                )
    n = tally["n"] or 1
    print(
        f"pilot {tally['n']}: agrees with gold {tally['agree'] / n:.1%},"
        f" same on repeat {tally['same'] / n:.1%}, errors {tally['error']}"
    )
    for f in FIELDS:
        print(f"{f:>12}: agrees {tally[f] / n:.1%}")
    return tally


def balance(exs: list[dict]) -> str:
    rows = [
        f"examples {len(exs)}: real {sum(not e.get('planted') for e in exs)}, "
        f"planted {sum(bool(e.get('planted')) for e in exs)}, "
        f"held out {sum(e['held_out'] for e in exs)} (never sent)"
    ]
    rows.append(
        "by sport: "
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(e["sport"] for e in exs).items()))
    )
    for f in FIELDS:
        c = Counter(e["gold"][f] for e in exs)
        rows.append(f"{f:>12}: " + ", ".join(f"{k} {c[k]}" for k in ("ok", "wrong", "not_said")))
    return "\n".join(rows)


def score(exs: list[dict], path: str) -> dict:
    """Outputs against gold on the held-out set, field by field."""
    want = {e["id"]: e["gold"] for e in exs if e["held_out"]}
    n, bad, exact, right = 0, 0, 0, Counter()
    with open(path, encoding="utf-8") as f:
        for row in map(json.loads, filter(str.strip, f)):
            if row["id"] not in want:
                continue
            n += 1
            got = parse(row["output"])
            if got is None:
                bad += 1
                continue
            exact += got == want[row["id"]]
            right.update(k for k in FIELDS if got[k] == want[row["id"]][k])
    return {
        "scored": n,
        "unparsed": bad,
        "exact": exact,
        **{f: right[f] for f in FIELDS},
    }


def main(argv=None, env=os.environ) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.seed_linecheck", description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", help="the default: FakeProvider, no network")
    mode.add_argument("--go", type=int, metavar="N", help="N recorded calls through Mubit")
    mode.add_argument("--pilot", type=int, metavar="N", help="N unkept examples, each sent twice")
    mode.add_argument("--score", metavar="MODEL_OUTPUTS.jsonl")
    mode.add_argument("--held-out", action="store_true", help="print the held-out set as jsonl")
    p.add_argument("--lines", help="a lines.jsonl copy, instead of the store")
    a = p.parse_args(argv)
    if a.lines:
        with open(a.lines, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
    else:
        lines = open_store(env).all("lines")
    exs = examples(lines)
    if a.score:
        r = score(exs, a.score)
        n = r["scored"] or 1
        print(
            f"held-out scored {r['scored']}, unparsed {r['unparsed']}, exact {r['exact'] / n:.1%}"
        )
        for f in FIELDS:
            print(f"{f:>12}: {r[f] / n:.1%}")
        return 0
    if a.held_out:
        for e in (e for e in exs if e["held_out"]):
            print(json.dumps({**e, "request": request(e)}))
        return 0
    print(balance(exs))
    if a.go or a.pilot:
        key = env.get("MUBIT_API_KEY")
        if not key:
            print("--go and --pilot need MUBIT_API_KEY in the environment", file=sys.stderr)
            return 2
        provider = MubitProvider(key, record=True)
        if a.pilot:  # Mubit keeps the call's metadata only: nothing trains on a pilot
            provider.client = provider.client.with_options(
                default_headers={"x-middleware-record": "metadata"}
            )
            pilot(batch(exs, a.pilot), provider)
            return 0
        tally = go(batch(exs, a.go), provider)
    else:
        sample = batch(exs, 3)
        for e in sample:
            print(
                f"\n--- example {e['id']} (planted: {bool(e.get('planted'))}),"
                f" gold {dumps(e['gold'])}"
            )
            print(json.dumps(request(e), indent=1, ensure_ascii=False))
        print()
        tally = go(sample, FakeProvider())
    print("tally: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
