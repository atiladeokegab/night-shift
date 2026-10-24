"""The producer's review queue (#171): stored lead lines whose numbers their own moment's data
contradicts (insight.wrong_numbers), so the producer can fix them by hand and Mubit trains on the
fix (#161). The check flags, the producer corrects, Mubit learns. A fallback line is queued with
the model's failed try and the reasons the check gave when it was said (#204)."""

from core import insight

UNSAID = "the milestone is unsaid"  # leaving a milestone out is not a wrong number: not queued


def _key(line: dict) -> tuple:
    return line.get("match_id"), line.get("moment_idx"), (line.get("tried") or line["text"]).strip()


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
        try:  # a reply is checked over the Stat moment it was said over, as its fix goes
            over = insight.said_over(line, lambda _, ms=moments: ms)
        except StopIteration:  # said after a moment no longer in the match
            continue
        if over:
            m, past = over[-1], over[:-1]
        else:
            at = next(
                (i for i, x in enumerate(moments) if x["idx"] == line.get("moment_idx")), None
            )
            if at is None:
                continue
            m, past = moments[at], moments[:at]  # the replay's history: recent-play counts
            if m.get("type") == "Stat":  # the analyst's moment
                continue
        if line.get("tried"):  # the retry failed too and the fallback was said: a human's to fix
            text, wrong = line["tried"], line.get("wrong") or ["the retry failed the check"]
        else:
            text = line["text"]
            wrong = [w for w in insight.wrong_numbers(text, m, header, past) if UNSAID not in w]
        if not wrong:
            continue
        d = m.get("detail") or {}
        play = d.get("play") or (
            m["outcome"][0].upper() + m["outcome"][1:]  # a reply: what the analyst just said
            if over
            else ", ".join(filter(None, (m["type"], m.get("outcome"), insight._who(m))))
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
                "text": text,
                "wrong": wrong,
            }
        )
    return out
