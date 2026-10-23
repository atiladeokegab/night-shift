"""Does the trained adapter call a moment the way the big model does? Held-out matches only (A-8.1).

    set -a; . ~/private/night-shift/mubit.env; set +a
    MUBIT_ADAPTER_MODEL=<the adapter's model name in Mubit> uv run python -m eval.agreement

The adapter is tested only when it can be: the latest adapter record in the store says ready
(python -m eval.record_adapter), MUBIT_ADAPTER_MODEL names the model Mubit serves it as, and
MUBIT_API_KEY is set. Otherwise this prints "not tested: <reason>" and calls nothing. Both models
run with recording off, so held-out moments never become training examples.

Per moment the two lines agree when both exist, neither is late, the adapter names the same players
from the match as the big model, and it states no number that neither the big model's line nor the
moment has. An empty, skipped or late line on either side is a disagreement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

from agent import feed
from agent.commentator import MubitProvider, line_for
from core.stats import ADAPTER_NEEDED
from core.store import open_store
from scripts.replay_matches import FOOTBALL, pick

LATE_MS = 1500  # A-3.3's p95 bound on the first word


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _names(text: str, cast: set[str]) -> set[str]:
    """The players the line names, each matched by surname."""
    words = set(re.findall(r"[a-z]+", _fold(text)))
    return {n for n in cast if set(_fold(n).split()[-1:]) <= words}


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def disagreement(
    moment: dict, big: dict | None, adapter: dict | None, cast: set[str] | None = None
) -> str | None:
    """Why the adapter's line disagrees with the big model's, or None when they agree. `cast` is
    every player in the match, so naming the wrong one counts; the moment's players by default."""
    for side, line in (("big model", big), ("adapter", adapter)):
        if line is None:
            return f"{side} skipped"
        if not line.get("text", "").strip():
            return f"{side} empty"
        ms = line.get("first_word_ms")
        ms = line.get("latency_ms") if ms is None else ms
        if ms is not None and ms > LATE_MS:
            return f"{side} late ({ms} ms)"
    cast = cast or set(moment.get("players", {}).values())
    said, want = _names(adapter["text"], cast), _names(big["text"], cast)
    if said != want:
        return f"names {sorted(said)}, big model {sorted(want)}"
    known = _numbers(big["text"]) | _numbers(json.dumps([moment.get("score"), moment.get("clock")]))
    if extra := _numbers(adapter["text"]) - known:
        return f"states {sorted(extra)}"
    return None


def not_tested(store, env=os.environ) -> str | None:
    latest = (store.all("adapter") or [{}])[-1]
    status = latest.get("status", "not_trained")
    if status != "ready":
        kept = latest.get("kept")
        kept = "not recorded" if kept is None else kept
        return f"the adapter isn't trained (status {status}, kept {kept} of {ADAPTER_NEEDED})"
    if not env.get("MUBIT_ADAPTER_MODEL"):
        return "MUBIT_ADAPTER_MODEL is not set: the app has no way to call the adapter"
    if not env.get("MUBIT_API_KEY"):
        return "MUBIT_API_KEY is not set"
    return None


class Model:
    """A provider with the request's model swapped, e.g. for the adapter's name in Mubit."""

    def __init__(self, provider, model: str):
        self.provider, self.model = provider, model

    def call(self, request: dict) -> dict:
        return self.provider.call({**request, "model": self.model})


def _line(header: dict, moments: list[dict], idx: int, provider) -> dict | None:
    try:
        return line_for(header, moments, idx, provider)
    except Exception as exc:  # no line or a failed call: a skipped line, never a stopped run
        print(f"  skipped #{idx}: {exc!r}", file=sys.stderr)
        return None


def compare(matches, big, adapter, per_match: int = 10) -> dict:
    """matches: (header, moments) pairs. Each picked moment is called by both providers."""
    agree, misses = 0, []
    for header, moments in matches:
        by_idx = {m["idx"]: m for m in moments}
        cast = {name for m in moments for name in m.get("players", {}).values()}
        at = {m["idx"]: i for i, m in enumerate(moments)}
        for idx in pick(moments, per_match):
            ours = _line(header, moments, at[idx], big)
            theirs = _line(header, moments, at[idx], adapter)
            why = disagreement(by_idx[idx], ours, theirs, cast)
            if why is None:
                agree += 1
            else:
                misses.append({"match_id": header["match_id"], "idx": idx, "why": why})
    return {"agree": agree, "total": agree + len(misses), "disagreements": misses}


def held_out_matches(football: int, cricket: int):
    """Real held-out matches, which the replay script never sends to Mubit."""
    found = 0
    for comp, season in FOOTBALL:
        if found >= football:
            break
        for meta in feed.statsbomb_matches(comp, season):
            if feed.held_out("football", str(meta["match_id"])):
                yield feed.load("football", str(meta["match_id"]), meta)
                found += 1
                break
    archive, found = feed.cricsheet_zip(), 0
    ids = sorted((n[:-5] for n in archive.namelist() if n[:-5].isdigit()), key=int, reverse=True)
    for match_id in ids:  # newest first
        if found >= cricket:
            break
        if not feed.held_out("cricket", match_id):
            continue
        event = (json.loads(archive.read(f"{match_id}.json")).get("info") or {}).get("event") or {}
        if "T20 World Cup" in str(event.get("name", "")):
            yield feed.load("cricket", match_id)
            found += 1


def main(argv=None, env=os.environ) -> dict:
    p = argparse.ArgumentParser(prog="python -m eval.agreement", description=__doc__)
    p.add_argument("--football", type=int, default=2, help="held-out football matches")
    p.add_argument("--cricket", type=int, default=2, help="held-out cricket matches")
    p.add_argument("--per-match", type=int, default=10, help="moments compared per match")
    a = p.parse_args(argv)
    if reason := not_tested(open_store(env), env):
        print(f"not tested: {reason}")
        return {"tested": False, "reason": reason}
    big = MubitProvider(env["MUBIT_API_KEY"], record=False)
    adapter = Model(MubitProvider(env["MUBIT_API_KEY"], record=False), env["MUBIT_ADAPTER_MODEL"])
    matches = held_out_matches(a.football, a.cricket)
    report = compare(matches, big, adapter, a.per_match)
    for miss in report["disagreements"]:
        print(f"  disagree {miss['match_id']} #{miss['idx']}: {miss['why']}")
    print(f"agreement: {report['agree']} of {report['total']} moments")
    return {"tested": True, **report}


if __name__ == "__main__":
    main()
