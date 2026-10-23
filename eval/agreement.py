"""Does the trained adapter call a moment the way the big model does? Held-out matches only (A-8.1).

    set -a; . ~/private/night-shift/mubit.env; set +a
    MUBIT_ADAPTER_MODEL=<the adapter's model name in Mubit> uv run python -m eval.agreement

The adapter is tested only when it can be: the latest adapter record in the store says ready
(python -m eval.record_adapter), MUBIT_ADAPTER_MODEL names the model Mubit serves it as, and
MUBIT_API_KEY is set. Otherwise this prints "not tested: <reason>" and calls nothing. Both models
run with recording off, so held-out moments never become training examples.

Per moment the two lines agree only when their facts provably match: both exist, neither is late,
and they state the same numbers in the same order, name the same players in the same order and
carry the same outcome terms (goal, saved, out, not out, six, overtake, pit, ...). Anything
uncertain, and an empty, skipped or late line on either side, is a disagreement.
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


# Outcome terms, longest first so "not out" and "own goal" win over "out" and "goal". A negation
# just before a term ("doesn't score", "no goal") makes it "not <term>".
OUTCOMES = {
    "not out": r"not out",
    "run out": r"run out",
    "own goal": r"own goal",
    "no-ball": r"no[- ]ball",
    "free hit": r"free hit",
    "free throw": r"free throws?",
    "lights out": r"lights out",
    "safety car": r"safety car",
    "red flag": r"red flag",
    "flag": r"chequered flag|checkered flag",
    "last lap": r"last lap",
    "yellow card": r"yellow card|booked",
    "red card": r"red card|sent off",
    "three": r"three[- ]pointer|from three|from deep",
    "pit": r"pit stop|pits|pitted|pitting",
    "goal": r"goals?|scores?|scored|scoring|nets|netted",
    "miss": r"miss|misses|missed|off target|over the bar",
    "saved": r"save|saves|saved",
    "woodwork": r"post|crossbar|woodwork",
    "wide": r"wide|wides",
    "lbw": r"lbw",
    "caught": r"caught",
    "bowled": r"bowled",
    "stumped": r"stumped",
    "wicket": r"wickets?",
    "out": r"out",
    "six": r"six|sixes",
    "four": r"four|fours|boundary",
    "overtake": r"overtakes?|overtaken|overtaking",
    "lead": r"leads?|lead change|ahead",
    "win": r"wins?|won|winner|champions?",
    "penalty": r"penalty|penalties|spot kick",
    "dunk": r"dunks?|slams?",
    "steal": r"steals?|stolen",
    "block": r"blocks?|blocked",
    "foul": r"fouls?|fouled",
    "substitution": r"substitut\w*|comes on|replaces",
    "injury": r"injur\w*",
    "offside": r"offside",
    "rain": r"rain\w*|wet",
    "final": r"buzzer|final whistle|full time",
}
_OUTCOME = re.compile(
    r"\b(?:" + "|".join(f"(?P<t{i}>{p})" for i, p in enumerate(OUTCOMES.values())) + r")\b"
)
_TERMS = list(OUTCOMES)
_NEGATED = re.compile(r"(?:\bnot|\bno|\bnever|n't)\s+(?:\w+\s+)?$")


def _outcomes(text: str) -> set[str]:
    folded, found = _fold(text), set()
    for m in _OUTCOME.finditer(folded):
        term = _TERMS[int(m.lastgroup[1:])]
        found.add(
            f"not {term}" if term != "not out" and _NEGATED.search(folded[: m.start()]) else term
        )
    return found


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def _names(text: str, cast: set[str]) -> list[str] | None:
    """The players the line names, in order of first mention: a full name, or a surname only one
    player has. None when a surname could be more than one player."""
    folded, found, taken = _fold(text), [], []
    for name in sorted(cast, key=len, reverse=True):
        for m in re.finditer(rf"\b{re.escape(_fold(name))}\b", folded):
            if not any(m.start() in r for r in taken):
                found.append((m.start(), name))
                taken.append(range(m.start(), m.end()))
    surnames: dict[str, list[str]] = {}
    for name in cast:
        surnames.setdefault(_fold(name).split()[-1], []).append(name)
    for surname, names in surnames.items():
        for m in re.finditer(rf"\b{re.escape(surname)}\b", folded):
            if any(m.start() in r for r in taken):
                continue
            if len(names) > 1:
                return None
            found.append((m.start(), names[0]))
    order: list[str] = []
    for _, name in sorted(found):
        if name not in order:
            order.append(name)
    return order


def disagreement(
    moment: dict, big: dict | None, adapter: dict | None, cast: set[str] | None = None
) -> str | None:
    """Why the adapter's line disagrees with the big model's, or None when their facts provably
    match: the same numbers in the same order, the same players in the same order and the same
    outcome terms. Anything uncertain disagrees. `cast` is every player in the match, so naming the
    wrong one counts; the moment's players by default."""
    for side, line in (("big model", big), ("adapter", adapter)):
        if line is None:
            return f"{side} skipped"
        if not line.get("text", "").strip():
            return f"{side} empty"
        ms = line.get("first_word_ms")
        ms = line.get("latency_ms") if ms is None else ms
        if ms is not None and ms > LATE_MS:
            return f"{side} late ({ms} ms)"
    said, want = adapter["text"], big["text"]
    if _numbers(said) != _numbers(want):
        return f"numbers {_numbers(said)}, big model {_numbers(want)}"
    cast = cast or set(moment.get("players", {}).values())
    names, wanted = _names(said, cast), _names(want, cast)
    if names is None or wanted is None:
        return "a surname that could be more than one player"
    if names != wanted:
        return f"names {names}, big model {wanted}"
    if not _outcomes(want):
        return "no outcome to compare"
    if _outcomes(said) != _outcomes(want):
        return f"outcome {sorted(_outcomes(said))}, big model {sorted(_outcomes(want))}"
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
