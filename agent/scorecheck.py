"""Score check (#321): Line check's score field alone, as its own Mubit task. A version is graded
on matching Claude's answers, and Claude matched its own Line check answers only 95% of the time
(leader caused most misses), so this narrower task asks one question whose answer code computes
from the event data (eval/linecheck.py `gold`). tests/test_scorecheck.py pins this request's hash:
edit it on purpose only, since any change starts a new task."""

from __future__ import annotations

import json
from string import Template

MODEL = "claude-sonnet-5-5"  # Line check's model: proven on this key with this output format
LABELS = ("ok", "wrong", "not_said")
SPORTS = ("football", "basketball", "cricket")  # an F1 "score" is a lap: left out

SYSTEM = """You check one line of live sports commentary against the score at its moment. The check is a mechanical comparison: never judge style, and never use anything but the line and the score given.

The user message gives the Line, then the Sport, the Match and the Score, each on its own labelled row. Decide one field:
- score: every score or standing the line gives (in digits or words, "eighty-five to eighty-six", "three all", "one nil", "155 for 5", a margin such as "down one", a chase's runs needed, "goalless") against Score.

Answer exactly one label:
- ok: the line gives a score or standing, and every one it gives matches Score.
- wrong: the line gives a score or standing, and any one it gives contradicts Score.
- not_said: the line gives no score or standing.

Reply with one line of compact JSON and nothing else: no spaces, no code fence, no explanation. For example:
{"score":"wrong"}

Rules that decide the close cases:
- "two one" or "2-1" with no team order matches Score if those numbers are the score in either order.
- Who leads, trails or is level, with no number, is not a score: not_said.
- A player's own running count ("his 40th point", "her second goal") is not a score.
- When unsure whether the line gives a score, answer not_said."""  # noqa: E501

SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "string", "enum": list(LABELS)}},
    "required": ["score"],
    "additionalProperties": False,
}

MESSAGE = Template("Line: $line\nSport: $sport\nMatch: $match\nScore: $score")


def request(message: str, match_id: str, idx: int) -> dict:
    """Line check's request shape (agent/linecheck.py), one session per moment so a moment's
    near-identical lines fall on one side of Mubit's test split."""
    return {
        "model": MODEL,
        "max_tokens": 600,
        "system": SYSTEM,
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        "metadata": {"user_id": f"score-check-{match_id}-{idx}"},
        "messages": [{"role": "user", "content": message}],
    }


def build_request(header: dict, m: dict, text: str) -> dict:
    from agent.commentator import _match, _score

    msg = MESSAGE.substitute(
        line=text, sport=m["sport"], match=_match(header), score=_score(header, m)
    )
    return request(msg, m["match_id"], m["idx"])


def dumps(label: str) -> str:
    """The canonical answer: {"score":"ok"}."""
    return json.dumps({"score": label}, separators=(",", ":"))


def parse(text: str) -> str | None:
    """The label, or None unless the reply is one JSON object holding only a known label."""
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(out, dict) or list(out) != ["score"] or out["score"] not in LABELS:
        return None
    return out["score"]


def teach(line: dict, sent: set[str] = frozenset(), provider=None) -> dict | None:
    """A producer's fix (agent/linecheck.py TEACHES) as one recorded Score check example: the line
    as first said and its score label from the event data, with the correction turn when Claude's
    reply differs. None, and no call, when code can't label it, for a held-out match, a stat line,
    an example already in `sent`, or no recorder (the owner's key, else the lines' provider)."""
    from agent.commentator import correction_provider, default_provider
    from data.matches import load_moments, match_header
    from eval.linecheck import HELD_OUT, example_id, gold
    from eval.seed_scorecheck import send

    mid, idx, text = line.get("match_id"), line.get("moment_idx"), line.get("tried") or line["text"]
    if mid in HELD_OUT or line.get("speaker") == "analyst" or "reply" in line or "insight" in line:
        return None
    if example_id(mid, idx, text) in sent:
        return None
    if provider is None:
        provider = correction_provider() or default_provider()
        if not getattr(provider, "record", False):
            return None
    try:
        header, moments = match_header(mid), load_moments(mid)
    except KeyError:  # not a bundled match: no facts to check against
        return None
    i = next((i for i, m in enumerate(moments) if m["idx"] == idx), None)
    if i is None or moments[i]["sport"] not in SPORTS:
        return None
    key = gold(header, moments[i], moments[:i], text)
    if key is None:
        return None
    ex = {"id": example_id(mid, idx, text), "match_id": mid, "idx": idx, "text": text}
    return send({**ex, "gold": key["score"]}, provider)
