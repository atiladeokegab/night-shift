"""The correction ledger: every example sent to Mubit's Score check (the answer key's seeding and a
producer's fix) and every auto-fix, newest first, each naming the Mubit session and request it went
in so it can be found in Mubit's console. Built from the store's own records (scorecheck_examples,
auto_fixes): nothing new is written. "Sent", never "kept": only the console says what Mubit kept."""

import threading
import time
from weakref import WeakKeyDictionary

from agent.commentator import _score, session_id
from core import insight
from core.review import UNSAID

# Mubit's console page for one request, with {session} and {request} filled in per row. Empty until
# a real console URL is known: no row gets a link.
MUBIT_REQUESTS_URL = ""

SOURCES = {"seed": "answer key", "fix": "human"}
SHOWN = 50  # the newest rows, all the review page shows
TTL_S = 30.0  # a built ledger is served this long: a poller costs nothing

_cache = WeakKeyDictionary()  # per store: when built, what
_cache_lock = threading.Lock()

# Seeded examples sent before a row named its line (planted ones too), by example id. Ids are
# content hashes, so a found one never changes. shortcut: rebuilt (about 6 s on 6k lines) while a
# shown row is unfound and the lines grew; fine while every old row is found, as on 24 Oct.
_seeded: dict[str, dict] = {}
_seeded_at = -1


def cached(store, deps) -> dict:
    """The ledger, built at most once per TTL_S per store."""
    with _cache_lock:
        now = time.monotonic()
        at, got = _cache.get(store, (None, None))
        if at is None or now - at >= TTL_S:
            got = ledger(store, deps)
            _cache[store] = now, got
        return got


def ledger(store, deps) -> dict:
    """{"sent": examples sent to Score check, "rows": the newest SHOWN corrections}. A row's
    `wrong` is what the number check finds wrong in the line, and `score` the data's score."""
    examples = store.all("scorecheck_examples")
    picks = sorted(
        [(True, r) for r in examples] + [(False, r) for r in store.all("auto_fixes")],
        key=lambda p: p[1].get("created_at") or "",
        reverse=True,
    )[:SHOWN]
    lines = store.all("lines")
    by_id = {ln["line_id"]: ln for ln in lines}
    by_text: dict[str, list[dict]] = {}
    for ln in lines:
        if ln.get("retried") and ln.get("text"):
            by_text.setdefault(ln["text"], []).append(ln)
    old = [r["id"] for sc, r in picks if sc and not r.get("text") and not r.get("line_id")]
    seeded(lines, old)
    titles = {m["match_id"]: m["title"] for m in deps.list_matches()}
    matches: dict = {}

    def facts(mid, idx, text) -> dict:
        """The data's score at the moment and what the check finds wrong in the line."""
        if mid not in matches:
            from data.matches import match_header

            try:
                matches[mid] = match_header(mid), deps.load_moments(mid)
            except (KeyError, FileNotFoundError):  # a match no longer bundled
                matches[mid] = None
        at = matches[mid] and next(
            (i for i, m in enumerate(matches[mid][1]) if m["idx"] == idx), None
        )
        if at is None:
            return {"sport": None, "score": None, "wrong": []}
        header, moments = matches[mid]
        m, past = moments[at], moments[:at]
        wrong = text and insight.wrong_numbers(text, m, header, past)
        wrong = [w for w in wrong or [] if UNSAID not in w]
        return {"sport": m["sport"], "score": _score(header, m), "wrong": wrong}

    def row(r: dict, ln: dict | None, text: str | None, **more) -> dict:
        ln = ln or {}
        mid = r.get("match_id") or ln.get("match_id")
        idx = r.get("idx", ln.get("moment_idx", ln.get("idx")))
        return {
            "at": r.get("created_at"),
            "match_id": mid,
            "match": titles.get(mid, mid),
            "idx": idx,
            "text": text,
            "request_id": r.get("mubit_request_id"),
            **facts(mid, idx, text),
            **more,
        }

    out = []
    for score_check, r in picks:
        if score_check:
            ln = by_id.get(r.get("line_id")) or _seeded.get(r["id"]) or {}
            text = r.get("text") or ln.get("tried") or ln.get("text")
            source = SOURCES.get(r.get("source"), r.get("source"))
            x = row(r, ln, text, task="Score check", source=source)
            x.update(kind=r.get("kind"), gold=r.get("gold"))
            x["session"] = f"score-check-{x['match_id']}-{x['idx']}" if x["text"] else None
        else:
            # The rejected line is the auto-fix's identity. Older rows may lack it in the store;
            # corrected text is safe only when every matching retry names the same moment.
            ln = by_id.get(r.get("line_id"))
            if ln is None:
                candidates = by_text.get(r.get("corrected_text"), [])
                identities = {
                    (candidate.get("match_id"), candidate.get("moment_idx", candidate.get("idx")))
                    for candidate in candidates
                }
                if candidates and len(identities) == 1:
                    ln = candidates[0]
            x = row(r, ln, None, task="Commentator", source="auto-fixed")
            x.update(fixed=r.get("corrected_text"), recorded=r.get("recorded", False))
            # the check's reasons, as the correction turn gave them (rows since #245 keep it)
            said = (r.get("correction") or "").split("\n")[0].removeprefix("Producer correction: ")
            x["wrong"] = said.removeprefix("number check: ").split("; ") if said else []
            x["session"] = session_id(x["sport"], x["match_id"]) if x["sport"] else None
        x["link"] = (
            MUBIT_REQUESTS_URL.format(session=x["session"], request=x["request_id"] or "")
            if MUBIT_REQUESTS_URL and x["session"]
            else None
        )
        out.append(x)
    return {"sent": len(examples), "rows": out}


def seeded(lines: list[dict], unfound: list[str]) -> None:
    """Find the seeded examples these ids name, from the lines they were made from."""
    global _seeded_at
    if all(i in _seeded for i in unfound) or len(lines) == _seeded_at:
        return
    from eval.seed_scorecheck import examples

    _seeded_at = len(lines)
    _seeded.update((e["id"], e) for e in examples(lines))
