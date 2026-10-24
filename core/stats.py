"""Proof-panel numbers, computed from the store only."""

import json
import threading
import time
import weakref
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

# USD per 1M tokens (input, output), list price
PRICES = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5-5": (2.00, 10.00)}
# USD per 1k characters: ElevenLabs API Starter ($6 for 75k v3); flash half (checked 2026-10-24)
VOICE_PRICES = {
    "eleven_v3": 0.08,
    "eleven_multilingual_v2": 0.08,
    "eleven_flash_v2_5": 0.04,
    "eleven_turbo_v2_5": 0.04,
}
# eval/agreement.py's floor of kept examples; nothing here enforces it, so /stats doesn't report it
ADAPTER_NEEDED = 25
# Line check beside the rules on held-out labelled lines (#317): eval/linecheck_eval.py --json
HELDOUT = Path(__file__).parent.parent / "eval" / "linecheck_heldout.json"
# Mubit's console overview as read by hand on a stated day (#317): a dated reading, never live data
CONSOLE = Path(__file__).parent.parent / "data" / "mubit_console.json"
# one computation serves every replay's lines and every /stats poll this long: stats() parses the
# whole store, and once per line per replay it saturated the one CPU (Cloud Run 429s, 24 Oct)
STATS_EVERY_S = 2.0
_recent: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # store: (when, stats)
_recent_lock = threading.Lock()


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def _cost(line: dict) -> float | None:
    if not line.get("model"):  # no model call: a line said from a producer's fix (#232) costs 0
        return 0.0
    price = PRICES.get(line.get("model"))
    if price is None:
        return None
    return (line.get("tokens_in", 0) * price[0] + line.get("tokens_out", 0) * price[1]) / 1e6


def _by_task(store) -> dict[str, dict]:
    """Each Mubit task's latest adapter record. eval/record_adapter.py appends {task, status, ...}
    from Mubit's console; a record from before #209's tasks carries no task: it was commentary's."""
    return {r.get("task", "commentary"): r for r in store.all("adapter")}


def _state(r: dict) -> tuple[str, str]:
    """What the latest record says, and only that: "passed" only when Mubit's gate was recorded as
    passed for a recorded version, "testing" once a version, score or failed gate is recorded,
    else "collecting"."""
    try:
        when = datetime.fromisoformat(r["created_at"]).astimezone(UTC)
        as_of = f", as of {when:%-d %b %Y %H:%M} UTC"
    except (KeyError, TypeError, ValueError):  # no record, or one from before created_at
        as_of = ""
    score, target = r.get("score"), r.get("target")
    of = f" of a {target:g}% target" if target is not None else ""
    best = f"{score:g}%{of}" if score is not None else ""
    # a pass names the version that passed (#333): a versionless pass reads as testing, never passed
    if r.get("passed") is True and r.get("version") is not None:
        scored = f", {best}" if best else ""
        return "passed", f"Passed Mubit's test (v{r['version']}){scored}{as_of}."
    if r.get("version") is not None or score is not None or r.get("passed") is False:
        scored = f"; best {best}" if best else ""
        return "testing", f"Testing: no version passed{scored}{as_of}."
    return "collecting", f"Collecting: no adapter version recorded yet{as_of}."


def _adapter(latest: dict) -> dict:
    state, summary = _state(latest)
    # no raw `status`: the console's word ("training") beside "collecting" read as a contradiction
    return {
        "state": state,
        "summary": summary,
        # a stored line doesn't prove Mubit kept it: unknown until a console count is recorded
        "kept": latest.get("kept"),
        "agree": latest.get("agree"),
        "total": latest.get("total"),
        # the app can't call the adapter, so its cost per line isn't measurable
        "cost_measurable": False,
        "console": json.loads(CONSOLE.read_text()) if CONSOLE.exists() else None,
    }


def _versions(records: list[dict], task: str) -> list[dict]:
    """Each version the task's records name, oldest first, as its latest record says it (#321)."""
    by = {}
    for r in records:
        if r.get("task", "commentary") == task and r.get("version") is not None:
            by[r["version"]] = {
                k: r.get(k) for k in ("version", "version_id", "score", "target", "passed")
            } | {"recorded_at": r.get("created_at"), "source": r.get("source")}
    return [by[v] for v in sorted(by)]


def _adapters(by_task: dict[str, dict], records: list[dict]) -> dict:
    # only what a record says: a field the console reading left out stays None, never inferred
    return {
        task: {
            "state": _state(r)[0],
            "version": r.get("version"),
            "version_id": r.get("version_id"),
            "score": r.get("score"),
            "target": r.get("target"),
            # a verdict with no version says nothing about any adapter (#321 review)
            "passed": r.get("passed") if r.get("version") is not None else None,
            "kept": r.get("kept"),
            "recorded_at": r.get("created_at"),
            "source": r.get("source"),
            "versions": _versions(records, task),
        }
        for task, r in by_task.items()
    }


# a ledger row's source, as the card names it: the match data's answer key, the number check's
# own retry, or a producer's fix
SOURCES = {"seed": "answer_key", "auto": "auto_fixed", "fix": "human"}


def _scorecheck(store, recorded: dict | None) -> dict:
    """Score check (#321), the one task trained (#363): the examples sent to Mubit by source, each
    model's latest score on the frozen held-out lines (eval/seed_scorecheck.py --score --record),
    and the last version read off the console by hand (eval/record_adapter.py), None until then."""
    sent = store.all("scorecheck_examples")
    fixes = [r for r in sent if r.get("source") == "fix"]
    held = {e["what"]: e for e in store.all("scorecheck_evals")}
    by_source = Counter(SOURCES.get(r.get("source")) for r in sent)
    return {
        "examples_sent": len(sent),
        "by_source": {name: by_source[name] for name in SOURCES.values()},
        "from_fixes_by_kind": dict(Counter(r["kind"] for r in fixes)),
        # keyed by model: an SSE event's JSON carries no "[" (tests/test_core_voice.py)
        "held_out": {
            what: {k: e.get(k) for k in ("agree", "scored", "unparsed")}
            | {"recorded_at": e.get("created_at")}
            for what, e in held.items()
        },
        # shortcut: a fixed time (Mubit's daily limit resets at 01:00 UK); edit it if training moves
        "next_training": "after 01:00 UK",
        "recorded": recorded,
    }


def _speaker(lines: list[dict]) -> dict:
    first = [ln["first_word_ms"] for ln in lines if ln.get("first_word_ms") is not None]
    costs = [c for c in map(_cost, lines) if c is not None]
    return {
        # one string, not a list: a `stats` event carries no brackets (a TTS tag must never show)
        "model": ", ".join(sorted({ln["model"] for ln in lines if ln.get("model")})),
        # the models Mubit's replies named (#250), as they named them
        "served_by": ", ".join(sorted({ln["served_by"] for ln in lines if ln.get("served_by")})),
        # the rest predate #250 or were built from the data: "Served by" alone would claim them
        "served_lines": sum(1 for ln in lines if ln.get("served_by")),
        "lines": len(lines),
        "first_word_ms_p50": _pct(first, 0.5),
        "first_word_ms_p95": _pct(first, 0.95),
        "cost_per_line_usd": sum(costs) / len(costs) if costs else None,
    }


def _heard(lines: list[dict], voice: list[dict]) -> dict:
    """Moment to audio ready (#233), for the lead only: an analyst line is called and checked
    before its stat moment is published, so its figure would leave all of that out."""
    ids = {ln.get("line_id") for ln in lines}
    # a line with no audio has no voice record with a time: left out, never counted as 0
    heard = [
        # audio ready before the video reached its moment: no wait
        max(0, v["audio_first_ms"])
        for v in voice
        if v.get("line_id") in ids and "audio_first_ms" in v
    ]
    return {
        "audio_first_ms_p50": _pct(heard, 0.5),
        "audio_first_ms_p95": _pct(heard, 0.95),
        "audio_lines": len(heard),
    }


def _per_match(store, lines: list[dict], voice: list[dict]) -> dict:
    """Mean spend of a full replay (one played from kick-off, #174): the model cost of every line
    it said, cached or not, and of its answers, plus its voice characters. A part is None when any
    of it has no known price. A record from before line_ids can't be costed and isn't counted."""
    full = [r for r in store.all("replays") if "line_ids" in r]
    matches = {r["replay_id"] for r in full}
    by_id = {ln.get("line_id"): ln for ln in lines}
    said = [by_id[i] for r in full for i in r["line_ids"] if i in by_id]
    said += [a for a in store.all("answers") if a.get("replay_id") in matches]
    model = [_cost(x) for x in said]
    spoken = [v for v in voice if v.get("replay_id") in matches]
    prices = [VOICE_PRICES.get(v.get("model")) for v in spoken]
    n = len(matches)
    model_usd = sum(model) / n if n and None not in model else None
    voice_usd = None  # no voice record: browser speech, or nothing measured to say it costs 0
    if spoken and None not in prices:
        voice_usd = sum(v["chars"] * p / 1000 for v, p in zip(spoken, prices, strict=True)) / n
    both = model_usd is not None and voice_usd is not None
    return {
        "matches_measured": n,
        "cost_per_match_usd": model_usd + voice_usd if both else None,
        "model_cost_per_match_usd": model_usd,
        "voice_cost_per_match_usd": voice_usd,
    }


def _autonomy(calls: list[dict]) -> dict:
    """The lead's checked calls by how the number check left them (#204): passed first time, fixed
    by the retry, or sent to a human (the retry failed too: the fallback was said, the try queued).
    """
    human = sum(bool(ln.get("fallback")) for ln in calls)
    auto = sum(bool(ln.get("retried")) and not ln.get("fallback") for ln in calls)
    n = len(calls)
    return {"called": n, "first_time": n - auto - human, "auto_fixed": auto, "to_human": human}


def _linecheck(store) -> dict:
    """Line check's second opinion on live lead lines (#298). Every live check is on a line the
    rules check passed when it was said, so each flag is one the rules missed."""
    checks = store.all("linechecks")
    flags = sum(bool(c.get("wrong")) for c in checks)
    # producer fixes sent as training examples; a failed send (kind "error") is no example
    sent = [x for x in store.all("linecheck_fixes") if x.get("kind") != "error"]
    today = [
        x for x in sent if x.get("created_at", "")[:10] == datetime.now(UTC).date().isoformat()
    ]
    return {
        "checked": len(checks),
        "flags": flags,
        "rules_missed": flags,
        "fixes_sent": len(sent),
        "examples_today": len(today),  # UTC day
        "examples_today_by_kind": dict(Counter(x["kind"] for x in today)),
        "heldout": json.loads(HELDOUT.read_text()) if HELDOUT.exists() else None,
    }


def _stats(store) -> dict:
    lines = store.all("lines")
    fixes = store.all("fixes")
    # a stat line between moments is the analyst's; a line with no speaker predates #130: the lead
    analyst = [ln for ln in lines if ln.get("speaker") == "analyst"]
    lead = [ln for ln in lines if ln.get("speaker") != "analyst"]
    adapters = _by_task(store)
    commentary = adapters.get("commentary", {})
    since = commentary.get("created_at", "")
    tasks = _adapters(adapters, store.all("adapter"))
    # only a fix Mubit recorded for training counts; one stored before #161 carries no flag
    recorded = [f for f in fixes if f.get("recorded") is True]
    first = [ln["first_word_ms"] for ln in lines if ln.get("first_word_ms") is not None]
    total = [ln["latency_ms"] for ln in lines if ln.get("latency_ms") is not None]
    voice = store.all("voice")
    costs = [c for c in map(_cost, lines) if c is not None]
    # the moment calls the check saw: a line from before `checked` was stored never counts as a pass
    calls = [ln for ln in lead if ln.get("checked") and "reply" not in ln]
    by_match: dict[str, list[dict]] = {}
    for ln in calls:
        by_match.setdefault(ln.get("match_id") or "", []).append(ln)
    return {
        "lines": len(lines),
        "fixes": len(fixes),
        "mubit_requests": len({r for ln in lines for r in ln.get("mubit_request_ids", [])}),
        "first_word_ms_p50": _pct(first, 0.5),
        "first_word_ms_p95": _pct(first, 0.95),
        "latency_ms_p50": _pct(total, 0.5),
        "latency_ms_p95": _pct(total, 0.95),
        "tokens_in": sum(ln.get("tokens_in", 0) for ln in lines),
        "tokens_out": sum(ln.get("tokens_out", 0) for ln in lines),
        "cost_per_line_usd": sum(costs) / len(costs) if costs else None,
        "by_speaker": {"lead": _speaker(lead) | _heard(lead, voice), "analyst": _speaker(analyst)},
        "fixes_recorded": len(recorded),
        # recorded since commentary's latest adapter record: the corrections toward the next one
        # whose corrected reply passed the number check (#245; a fix before it has no flag)
        "fixes_toward_next": sum(
            f.get("created_at", "") > since and f.get("reply_passed") is not False for f in recorded
        ),
        # every correction the number check sent to Mubit (#162), not a person's; it also counts
        # retries from before #204 stored `retried`, which autonomy's auto_fixed leaves out
        "fixes_auto_sent": len(store.all("auto_fixes")),
        "spoken_from_fix": sum(1 for ln in lead if ln.get("fixed")),  # a producer's fix (#232)
        "voice_chars": sum(v.get("chars", 0) for v in voice),
        "autonomy": _autonomy(calls),
        "autonomy_by_match": {m: _autonomy(c) for m, c in by_match.items()},
        "linecheck": _linecheck(store),
        "scorecheck": _scorecheck(store, tasks.pop("score_check", None)),
        # the commentary tasks trained before Score check (#363): kept, never the headline
        "earlier_tasks": {"adapter": _adapter(commentary), "adapters": tasks},
        **_per_match(store, lines, voice),
    }


def stats(store, fresh: bool = False) -> dict:
    """The proof panel, computed at most once every STATS_EVERY_S however many replays and pages
    ask; a caller arriving mid-computation waits for it instead of starting another. `fresh`
    computes now (a fix must show at once), and the next callers get that."""
    with _recent_lock:
        at, made = _recent.get(store, (None, None))
        if fresh or at is None or time.monotonic() - at >= STATS_EVERY_S:
            made = _stats(store)
            _recent[store] = (time.monotonic(), made)
        return made
