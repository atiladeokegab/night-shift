"""Seed and measure the Score check task (#321, agent/scorecheck.py) on Mubit. Every example's
answer is code's score label from the event data (eval/linecheck.py `gold`); a line code can't
label is never sent. Lines of the held-out matches (3913122, 9636) never go: the unseen test set.

    uv run python -m eval.seed_scorecheck --dry                  # FakeProvider, no network
    uv run python -m eval.seed_scorecheck --pilot 50             # two unkept calls each
    uv run python -m eval.seed_scorecheck --go 150               # recorded; skips any already sent
    uv run python -m eval.seed_scorecheck --fixes                # every stored fix, recorded
    uv run python -m eval.seed_scorecheck --held-out > eval/scorecheck_heldout.jsonl  # froze it
    uv run python -m eval.seed_scorecheck --claude out.jsonl     # Claude on held-out, unrecorded
    uv run python -m eval.seed_scorecheck --score out.jsonl --record "Claude Sonnet 5.5, API"

Lines come from the store (MODE=cloud STORE_URL=gs://... for the deployed one), or `--lines FILE`.
`--go` writes each sent example to the store's `scorecheck_examples` ledger, so a rerun sends only
new ones. `--score --record` keeps the result in `scorecheck_evals` for /stats, with its source.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from itertools import zip_longest

from agent.commentator import CORRECTION, FakeProvider, MubitProvider
from agent.scorecheck import LABELS, SPORTS, build_request, dumps, parse
from core.store import open_store
from data.matches import load_moments, match_header
from eval.linecheck import HELD_OUT, example_id, plant
from eval.seed_linecheck import WORKERS, _text
from eval.seed_linecheck import examples as line_examples

SEED = 321
HELD = "eval/scorecheck_heldout.jsonl"  # `--held-out` from the 24 Oct 20:00Z store, frozen


def examples(lines: list[dict]) -> list[dict]:
    """Line check's labelled lines (eval/seed_linecheck.py), each with its score label, and for a
    line that gives the score right, one planted copy with a score number changed (gold wrong)."""
    cache, out = {}, []
    for e in line_examples(lines):
        if e.get("planted") or e["sport"] not in SPORTS:
            continue
        mid = e["match_id"]
        if mid not in cache:
            cache[mid] = match_header(mid), load_moments(mid)
        header, moments = cache[mid]
        i = next(i for i, m in enumerate(moments) if m["idx"] == e["idx"])
        base = {k: e[k] for k in ("match_id", "sport", "idx", "held_out")}
        out.append({**base, "id": e["id"], "text": e["text"], "gold": e["gold"]["score"]})
        if e["gold"]["score"] == "ok":
            p = plant(header, moments[i], moments[:i], e["text"], e["gold"], "score")
            if p:
                pid = example_id(mid, e["idx"], p)
                out.append({**base, "id": pid, "text": p, "gold": "wrong", "planted": True})
    return out


def request(ex: dict) -> dict:
    header, moments = match_header(ex["match_id"]), load_moments(ex["match_id"])
    return build_request(header, next(m for m in moments if m["idx"] == ex["idx"]), ex["text"])


def batch(exs: list[dict], n: int) -> list[dict]:
    """The first n training examples, the labels taken in turn from a fixed shuffle so not_said
    (the rarest) isn't swamped; a held-out match's line never. A larger n keeps the smaller's."""
    train = [e for e in exs if not e["held_out"] and e["match_id"] not in HELD_OUT]
    random.Random(SEED).shuffle(train)
    by = [[e for e in train if e["gold"] == g] for g in LABELS]
    return [e for row in zip_longest(*by) for e in row if e][:n]


def send(ex: dict, provider) -> dict:
    """One recorded example: the request, and when Claude's reply isn't the gold, the correction
    turn with the gold's exact JSON (as Line check's seeding and a producer's fix do). The kind is
    matched, corrected, uncorrected or error; the request id is the last call's."""
    req, want, ids = request(ex), dumps(ex["gold"]), []
    try:
        reply = provider.call(req)
        ids.append(reply.get("request_id"))
        said = _text(reply)
        kind = "matched"
        if parse(said) != ex["gold"]:
            req["messages"] += [
                {"role": "assistant", "content": said or "(no reply)"},
                {"role": "user", "content": CORRECTION.format(text=want)},
            ]
            reply = provider.call(req)
            ids.append(reply.get("request_id"))
            kind = "corrected" if parse(_text(reply)) == ex["gold"] else "uncorrected"
    except Exception as exc:  # one failed call never stops the batch; the key is never printed
        print(f"ERR {ex['id']} {type(exc).__name__}", file=sys.stderr, flush=True)
        kind = "error"
    return {
        "id": ex["id"],
        "match_id": ex["match_id"],  # the line it was, for the ledger (core/ledger.py)
        "idx": ex["idx"],
        "text": ex["text"],
        "kind": kind,
        "gold": ex["gold"],
        "mubit_request_id": ids[-1] if ids else None,
    }


def go(exs: list[dict], provider, store, source: str = "seed", workers: int = WORKERS) -> Counter:
    """Send each example not yet in the ledger; a sent one (not an error) is written to it."""
    done = {r["id"] for r in store.all("scorecheck_examples")}
    todo = [e for e in exs if e["id"] not in done]
    tally = Counter(skipped=len(exs) - len(todo))
    with ThreadPoolExecutor(workers) as pool:
        for row in pool.map(lambda e: send(e, provider), todo):
            tally[row["kind"]] += 1
            if row["kind"] != "error":  # an error is sent again next run
                at = datetime.now(UTC).isoformat(timespec="seconds")
                store.append("scorecheck_examples", {**row, "source": source, "created_at": at})
            print(f"REC {row['id']} {row['kind']}", flush=True)
    return tally


def send_fix(store, line: dict, corrected: str, teach) -> list[dict]:
    """A producer's fix as Score check examples: the line as said and the fixed text, each labelled
    from the data by `teach` (agent/scorecheck.py), each sent once ever; the rows written."""
    rows = []
    for said in (line, {**line, "tried": None, "text": corrected}):
        sent = teach(said, {r["id"] for r in store.all("scorecheck_examples")})
        if sent and sent["kind"] != "error":
            at = datetime.now(UTC).isoformat(timespec="seconds")
            row = {**sent, "line_id": line["line_id"], "source": "fix", "created_at": at}
            store.append("scorecheck_examples", row)
            rows.append(row)
    return rows


def fixes(store, teach) -> Counter:
    """Every stored fix through send_fix: the ones made before a fix reached Score check."""
    lines = {ln["line_id"]: ln for ln in store.all("lines")}
    tally = Counter()
    for f in store.all("fixes"):
        if line := lines.get(f["line_id"]):
            tally.update(r["kind"] for r in send_fix(store, line, f["corrected_text"], teach))
    return tally


def pilot(exs: list[dict], provider, workers: int = WORKERS) -> Counter:
    """Two calls per example: does Claude give the gold, and the same answer again?"""

    def one(ex):
        try:
            a, b = (_text(provider.call(request(ex))) for _ in range(2))
        except Exception as exc:  # the key is never printed
            print(f"ERR {ex['id']} {type(exc).__name__}", file=sys.stderr)
            return None
        return parse(a) == ex["gold"], a == b, a, ex

    tally = Counter()
    with ThreadPoolExecutor(workers) as pool:
        for r in pool.map(one, exs):
            if r is None:
                tally["error"] += 1
                continue
            agree, same, said, ex = r
            tally.update(n=1, agree=agree, same=same)
            if not (agree and same):
                print(f"PILOT {ex['id']} gold={ex['gold']} reply={said!r} line={ex['text']!r}")
    n = tally["n"] or 1
    print(
        f"pilot {tally['n']}: agrees with gold {tally['agree']}/{tally['n']}"
        f" ({tally['agree'] / n:.1%}), same on repeat {tally['same']}/{tally['n']}"
        f" ({tally['same'] / n:.1%}), errors {tally['error']}"
    )
    return tally


def held_out(exs: list[dict]) -> list[dict]:
    return [e for e in exs if e["held_out"]]


def claude(exs: list[dict], provider, workers: int = WORKERS) -> list[dict]:
    """Claude's raw reply on each held-out line, as {"id", "output"}; a failed call is ""."""

    def one(ex):
        try:
            return {"id": ex["id"], "output": _text(provider.call(request(ex)))}
        except Exception as exc:  # the key is never printed
            print(f"ERR {ex['id']} {type(exc).__name__}", file=sys.stderr)
            return {"id": ex["id"], "output": ""}

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(one, held_out(exs)))


def score(exs: list[dict], rows: list[dict]) -> dict:
    """Outputs against the gold on held-out lines only: how many agree, and the misses by label."""
    want = {e["id"]: e["gold"] for e in held_out(exs)}
    seen = [r for r in rows if r["id"] in want]
    got = {r["id"]: parse(r["output"]) for r in seen}
    return {
        "scored": len(seen),
        "agree": sum(got[i] == want[i] for i in got),
        "unparsed": sum(g is None for g in got.values()),
        "held_out": len(want),
        "by_gold": {
            g: [sum(got[i] == g for i in got if want[i] == g), sum(want[i] == g for i in got)]
            for g in LABELS
        },
    }


def main(argv=None, env=os.environ) -> int:
    p = argparse.ArgumentParser(prog="python -m eval.seed_scorecheck", description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry", action="store_true", help="the default: FakeProvider, no network")
    mode.add_argument("--go", type=int, metavar="N", help="the first N examples, recorded")
    mode.add_argument("--pilot", type=int, metavar="N", help="N examples, each sent twice, unkept")
    mode.add_argument("--held-out", action="store_true", help="print the held-out set as jsonl")
    mode.add_argument("--claude", metavar="OUT.jsonl", help="Claude on held-out, unrecorded")
    mode.add_argument("--score", metavar="OUTPUTS.jsonl", help='{"id", "output"} per line')
    mode.add_argument("--fixes", action="store_true", help="every stored fix, recorded as live")
    p.add_argument("--record", metavar="WHAT", help="with --score: keep it for /stats, named")
    p.add_argument("--lines", help="a lines.jsonl copy, instead of the store")
    a = p.parse_args(argv)
    store = open_store(env)
    if a.fixes:  # the live fix's recorder: the owner's key, else the lines' when it records
        from agent.scorecheck import teach

        tally = fixes(store, teach)
        print("tally: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
        return 0
    if a.claude or a.score:  # the frozen set, so every model is scored on the same lines
        with open(HELD, encoding="utf-8") as f:
            exs = [json.loads(x) for x in f if x.strip()]
    elif a.lines:
        with open(a.lines, encoding="utf-8") as f:
            exs = examples([json.loads(x) for x in f if x.strip()])
    else:
        exs = examples(store.all("lines"))
    print(
        f"examples {len(exs)}: "
        + ", ".join(f"{g} {sum(e['gold'] == g for e in exs)}" for g in LABELS)
        + f"; held out {len(held_out(exs))} (never sent)",
        file=sys.stderr,
    )
    if a.held_out:
        for e in held_out(exs):
            print(json.dumps({**e, "message": request(e)["messages"][0]["content"]}))
        return 0
    if a.score:
        with open(a.score, encoding="utf-8") as f:
            r = score(exs, [json.loads(x) for x in f if x.strip()])
        print(json.dumps(r))
        if a.record:
            at = datetime.now(UTC).isoformat(timespec="seconds")
            store.append("scorecheck_evals", {"what": a.record, **r, "created_at": at})
        return 0
    if a.go or a.pilot or a.claude:
        key = env.get("MUBIT_API_KEY")
        if not key:
            print("--go, --pilot and --claude need MUBIT_API_KEY", file=sys.stderr)
            return 2
        provider = MubitProvider(key, record=bool(a.go))  # else recording off: nothing trains
    else:
        provider = FakeProvider()
    if a.pilot:
        pilot(batch(exs, a.pilot), provider)
    elif a.claude:
        with open(a.claude, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in claude(exs, provider))
    elif a.go:
        tally = go(batch(exs, a.go), provider, store)
        print("tally: " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    else:
        for e in batch(exs, 3):
            print(f"\n--- {e['id']} gold {dumps(e['gold'])}\n{json.dumps(request(e), indent=1)}")
            print("FakeProvider:", send(e, FakeProvider())["kind"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
