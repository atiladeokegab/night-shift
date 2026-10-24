"""The producer's review queue (#171): stored lead lines whose numbers their own moment's data
contradicts (insight.wrong_numbers), so the producer can fix them by hand and Mubit trains on the
fix (#161). The check flags, the producer corrects, Mubit learns."""

from core import insight

UNSAID = "the milestone is unsaid"  # leaving a milestone out is not a wrong number: not queued


def _key(line: dict) -> tuple:
    return line.get("match_id"), line.get("moment_idx"), line["text"].strip()


def queue(store, deps) -> list[dict]:
    """One entry per distinct (match, moment, text), newest first; a line whose text, at that
    moment, has been fixed under any of its line_ids is left out."""
    from agent.commentator import _score
    from data.matches import match_header

    lines = store.all("lines")
    fixed_ids = {f["line_id"] for f in store.all("fixes")}
    fixed = {_key(ln) for ln in lines if ln["line_id"] in fixed_ids}
    titles = {m["match_id"]: m["title"] for m in deps.list_matches()}
    matches: dict[str, tuple[dict, list[dict]] | None] = {}
    seen, out = set(), []
    for line in reversed(lines):  # appended in order: newest first
        if line.get("speaker") == "analyst" or not line.get("text"):
            continue
        k = _key(line)
        if k in seen or k in fixed:
            continue
        seen.add(k)
        mid = line.get("match_id")
        if mid not in matches:
            try:
                header = match_header(mid)
                matches[mid] = header, deps.load_moments(mid)
            except (KeyError, FileNotFoundError):  # a match no longer bundled: nothing to check
                matches[mid] = None
        if matches[mid] is None:
            continue
        header, moments = matches[mid]
        at = next((i for i, x in enumerate(moments) if x["idx"] == line.get("moment_idx")), None)
        if at is None:
            continue
        m, past = moments[at], moments[:at]  # past: as the replay's history, for recent-play counts
        if m.get("type") == "Stat":  # the analyst's moment
            continue
        wrong = [w for w in insight.wrong_numbers(line["text"], m, header, past) if UNSAID not in w]
        if not wrong:
            continue
        d = m.get("detail") or {}
        play = d.get("play") or ", ".join(
            filter(None, (m["type"], m.get("outcome"), insight._who(m)))
        )
        out.append(
            {
                "line_id": line["line_id"],
                "match_id": mid,
                "match": titles.get(mid, mid),
                "sport": m["sport"],
                "moment_idx": m["idx"],
                "clock": m.get("clock"),
                "period": m.get("period"),
                "score": _score(header, m),
                "play": play,
                "text": line["text"],
                "wrong": wrong,
            }
        )
    return out
