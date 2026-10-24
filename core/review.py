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


def _group(entry: dict) -> tuple:
    return entry["match_id"], entry["moment_idx"], tuple(entry["wrong"])


def queue(store, deps) -> list[dict]:
    """One card per mistake, newest first (#227): the distinct (match, moment, text) lines whose
    check gives the same reasons at the same moment are one entry, the newest line's, with `lines`
    (how many) and `others` (the older wordings, newest first). A fix on any line of a mistake
    clears the lines of it stored up to the fix; one said again after the fix is a new card."""
    lines = store.all("lines")
    fixes = {f["line_id"]: f.get("created_at") or "" for f in store.all("fixes")}
    fixed = {_key(ln) for ln in lines if ln["line_id"] in fixes}
    matches: dict = {}  # filled only when a line is new to the cache

    def check(line):
        record = json.dumps(line, sort_keys=True)
        if record not in _checked:
            _checked[record] = _entry(line, matches, deps)
        return _checked[record]

    cleared: dict[tuple, str] = {}  # each fixed mistake: when it was last fixed
    for line in lines:
        if line["line_id"] in fixes and line.get("speaker") != "analyst" and line.get("text"):
            if e := check(line):
                cleared[_group(e)] = max(cleared.get(_group(e), ""), fixes[line["line_id"]])
    seen, groups = set(), {}
    for line in reversed(lines):  # appended in order: newest first
        if line.get("speaker") == "analyst" or not line.get("text"):
            continue
        k = _key(line)
        if k in seen or k in fixed:
            continue
        seen.add(k)
        if not (e := check(line)):
            continue
        g = _group(e)
        if g in cleared and (line.get("created_at") or "") <= cleared[g]:
            continue
        if g in groups:
            groups[g]["lines"] += 1
            groups[g]["others"].append(e["text"])
        else:
            groups[g] = {**e, "lines": 1, "others": []}  # a copy: the cached entry stays as it is
    return list(groups.values())


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
