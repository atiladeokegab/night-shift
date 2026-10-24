"""The producer's review queue (#171): stored lead lines whose numbers their own moment's data
contradicts (insight.wrong_numbers), so the producer can fix them by hand and Mubit trains on the
fix (#161). The check flags, the producer corrects, Mubit learns. A fallback line is queued with
the model's failed try and the reasons the check gave when it was said (#204). Every other entry
is a line said before today's check, which today's check fails: marked `later_check` (#220)."""

import json

from core import insight

UNSAID = "the milestone is unsaid"  # leaving a milestone out is not a wrong number: not queued

# Each stored line's entry (or None), keyed by the whole record: a line never changes once
# appended, so only new lines are checked. shortcut: grows with the store (about 1 KB a line,
# 6k lines on 24 Oct); cleared on a deploy, which is also when the checker changes.
_checked: dict[str, dict | None] = {}


def _key(line: dict) -> tuple:
    return line.get("match_id"), line.get("moment_idx"), (line.get("tried") or line["text"]).strip()


def queue(store, deps) -> list[dict]:
    """One entry per distinct (match, moment, text), newest first; a line whose text, at that
    moment, has been fixed under any of its line_ids is left out."""
    lines = store.all("lines")
    fixed_ids = {f["line_id"] for f in store.all("fixes")}
    fixed = {_key(ln) for ln in lines if ln["line_id"] in fixed_ids}
    matches: dict = {}  # filled only when a line is new to the cache
    seen, out = set(), []
    for line in reversed(lines):  # appended in order: newest first
        if line.get("speaker") == "analyst" or not line.get("text"):
            continue
        k = _key(line)
        if k in seen or k in fixed:
            continue
        seen.add(k)
        record = json.dumps(line, sort_keys=True)
        if record not in _checked:
            _checked[record] = _entry(line, matches, deps)
        if _checked[record]:
            out.append(_checked[record])
    return out


def wrong(line: dict, text: str, deps) -> list[str]:
    """What the check finds wrong with `text` said in `line`'s place, at its moment (#232): a
    producer's fix that contradicts the data is never stored or sent for training."""
    keep = {k: v for k, v in line.items() if k not in ("tried", "wrong")}
    entry = _entry({**keep, "text": text}, {}, deps)
    return entry["wrong"] if entry else []


def _entry(line: dict, matches: dict, deps) -> dict | None:
    """The line's queue entry, or None when its numbers match its moment."""
    from agent.commentator import _score
    from data.matches import match_header

    if "titles" not in matches:
        matches["titles"] = {m["match_id"]: m["title"] for m in deps.list_matches()}
    mid = line.get("match_id")
    if mid not in matches:
        try:
            header = match_header(mid)
            matches[mid] = header, deps.load_moments(mid)
        except (KeyError, FileNotFoundError):  # a match no longer bundled: nothing to check
            matches[mid] = None
    if matches[mid] is None:
        return None
    header, moments = matches[mid]
    try:  # a reply is checked over the Stat moment it was said over, as its fix goes
        over = insight.said_over(line, lambda _, ms=moments: ms)
    except StopIteration:  # said after a moment no longer in the match
        return None
    if over:
        m, past = over[-1], over[:-1]
    else:
        at = next((i for i, x in enumerate(moments) if x["idx"] == line.get("moment_idx")), None)
        if at is None:
            return None
        m, past = moments[at], moments[:at]  # the replay's history: recent-play counts
        if m.get("type") == "Stat":  # the analyst's moment
            return None
    if line.get("tried"):  # the retry failed too and the fallback was said: a human's to fix
        text, wrong = line["tried"], line.get("wrong") or ["the retry failed the check"]
    else:
        text = line["text"]
        wrong = [w for w in insight.wrong_numbers(text, m, header, past) if UNSAID not in w]
    if not wrong:
        return None
    d = m.get("detail") or {}
    play = d.get("play") or (
        m["outcome"][0].upper() + m["outcome"][1:]  # a reply: what the analyst just said
        if over
        else ", ".join(filter(None, (m["type"], m.get("outcome"), insight._who(m))))
    )
    return {
        "line_id": line["line_id"],
        "match_id": mid,
        "match": matches["titles"].get(mid, mid),
        "sport": m["sport"],
        "moment_idx": m["idx"],
        "clock": m.get("clock"),
        "period": m.get("period"),
        "score": _score(header, m),
        "play": play,
        "text": text,
        "wrong": wrong,
        "later_check": not line.get("tried"),  # passed (or predates) the check when it was said
    }
