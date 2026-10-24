"""Does the trained adapter call a moment the way the big model does? Held-out matches only (A-8.1).

    set -a; . ~/private/night-shift/mubit.env; set +a
    MUBIT_ADAPTER_MODEL=<the adapter's model name in Mubit> uv run python -m eval.agreement

The adapter is tested only when it can be: the latest adapter record in the store says ready
(python -m eval.record_adapter), MUBIT_ADAPTER_MODEL names the model Mubit serves it as, and
MUBIT_API_KEY is set. Otherwise this prints "not tested: <reason>" and calls nothing. Both models
run with recording off, so held-out moments never become training examples.

The headline is strict agreement, a lower bound: a moment counts only when both lines exist, neither
is late, and they are the same words once lowercased, stripped of punctuation, with number words as
digits ("Two-nil!" and "2 nil"). Two rounds of review showed word-list fact matching lets
contradictions through, so it never scores. Under the headline, the fact checker lists possible
disagreements (different numbers, players, names or outcome terms) for the lines that don't match.
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
HEADLINE = "strict agreement (lower bound)"
HEADLINE_NOTE = (
    "counts only lines that state the same thing in the same words; true agreement is at least this"
)

_DIGITS = {
    w: str(i)
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen".split()
    )
} | {
    w: str(10 * i)
    for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split())
    if w != "_"
}


def normalise(text: str) -> str:
    """Lowercased, punctuation stripped, number words as digits, whitespace collapsed; no more."""
    words = re.sub(r"[^\w\s]|_", " ", text.lower()).split()
    return " ".join(_DIGITS.get(w, w) for w in words)


def _unusable(big: dict | None, adapter: dict | None) -> str | None:
    """Why a pair can't agree at all: a skipped, empty or late line on either side."""
    for side, line in (("big model", big), ("adapter", adapter)):
        if line is None:
            return f"{side} skipped"
        if not line.get("text", "").strip():
            return f"{side} empty"
        ms = line.get("first_word_ms")
        ms = line.get("latency_ms") if ms is None else ms
        if ms is not None and ms > LATE_MS:
            return f"{side} late ({ms} ms)"
    return None


def strict(big: dict | None, adapter: dict | None) -> str | None:
    """None when the two lines strictly agree (the headline); otherwise why not."""
    if why := _unusable(big, adapter):
        return why
    return None if normalise(adapter["text"]) == normalise(big["text"]) else "different words"


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


# Score words, so "one nil" and "two nil" differ. Three, four and six are left to the outcome terms.
_NUMBER_WORDS = {
    w: i
    for i, w in enumerate(
        "zero one two _ _ five _ seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split()
    )
    if w != "_"
} | {"nil": 0, "nought": 0}
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\b(?:" + "|".join(_NUMBER_WORDS) + r")\b")


def _numbers(text: str) -> list[str]:
    return [str(_NUMBER_WORDS.get(n, n)) for n in _NUMBER.findall(_fold(text))]


# Capitalised words that start a sentence without naming anyone or anything.
_COMMON = set(
    "a an and but he her his i in is it it's its just look no not now oh on over she so that "
    "that's the their there they this what what's wow yes".split()
)


def _others(text: str, cast: set[str]) -> list[str]:
    """The other names the line uses (teams, places, anyone outside the cast), folded, in order of
    first mention: its capitalised words, less the cast's names, common sentence starts, outcome
    terms and score words."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    for name in sorted(cast, key=len, reverse=True):
        plain = re.sub(rf"\b{re.escape(_fold(name))}\b", " ", plain, flags=re.I)
    for name in cast:
        plain = re.sub(rf"\b{re.escape(_fold(name).split()[-1])}\b", " ", plain, flags=re.I)
    order: list[str] = []
    for word in re.findall(r"[A-Za-z][\w']*", plain):
        low = word.lower()
        if word[0].isupper() and low not in order and low not in _COMMON | set(_NUMBER_WORDS):
            if not _OUTCOME.fullmatch(low):
                order.append(low)
    return order


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


def possible_disagreement(
    moment: dict, big: dict | None, adapter: dict | None, cast: set[str] | None = None
) -> str | None:
    """Diagnostics only, never the score: a factual difference between the two lines (numbers,
    players, other names, outcome terms), or None when it finds none, which proves nothing.
    `cast` is every player in the match, so naming the wrong one shows; the moment's by default."""
    if why := _unusable(big, adapter):
        return why
    said, want = adapter["text"], big["text"]
    if _numbers(said) != _numbers(want):
        return f"numbers {_numbers(said)}, big model {_numbers(want)}"
    cast = cast or set(moment.get("players", {}).values())
    names, wanted = _names(said, cast), _names(want, cast)
    if names is None or wanted is None:
        return "a surname that could be more than one player"
    if names != wanted:
        return f"names {names}, big model {wanted}"
    # Any other name the adapter adds must be the big model's or the moment's own team, and the
    # names both use must come in the same order ("Argentina lead France", not "France lead ...").
    others, wanted = _others(said, cast), _others(want, cast)
    team = _fold(moment.get("team") or "").split()
    if unknown := [w for w in others if w not in wanted and w not in team]:
        return f"names {unknown} the big model doesn't use"
    if [w for w in others if w in wanted] != [w for w in wanted if w in others]:
        return f"names in the order {others}, big model {wanted}"
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
    """matches: (header, moments) pairs. Each picked moment is called by both providers. `agree`
    counts strict agreement; `possible_disagreements` is what the fact checker finds in the rest."""
    agree, total, misses = 0, 0, []
    for header, moments in matches:
        by_idx = {m["idx"]: m for m in moments}
        cast = {name for m in moments for name in m.get("players", {}).values()}
        at = {m["idx"]: i for i, m in enumerate(moments)}
        for idx in pick(moments, per_match):
            ours = _line(header, moments, at[idx], big)
            theirs = _line(header, moments, at[idx], adapter)
            total += 1
            if strict(ours, theirs) is None:
                agree += 1
            elif why := possible_disagreement(by_idx[idx], ours, theirs, cast):
                misses.append({"match_id": header["match_id"], "idx": idx, "why": why})
    return {"agree": agree, "total": total, "possible_disagreements": misses}


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
    print(f"{HEADLINE}: {report['agree']} of {report['total']} moments ({HEADLINE_NOTE})")
    print(f"possible disagreements: {len(report['possible_disagreements'])}")
    for miss in report["possible_disagreements"]:
        print(f"  {miss['match_id']} #{miss['idx']}: {miss['why']}")
    return {"tested": True, **report}


if __name__ == "__main__":
    main()
