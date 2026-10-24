"""Line check (#209): the task as Mubit sees it, in one place for the seeding script and any later
caller. Mubit groups calls into one task only when the instructions, tools, output format and model
are byte-identical, so tests/test_linecheck.py pins this request's hash: edit it on purpose only.

The adapter is graded on matching Claude's answer exactly, so the answer is one canonical line:
compact JSON, fixed key order, no spaces, nothing else."""

from __future__ import annotations

import json
from string import Template

MODEL = "claude-sonnet-5-5"  # Haiku agreed with gold on 25% of a 40-line pilot; Sonnet 90%
FIELDS = ("score", "leader", "player_total", "event")
LABELS = ("ok", "wrong", "not_said")

SYSTEM = """You check one line of live sports commentary against the facts of its moment. The check is a mechanical comparison: never judge style, and never use anything but the line and the facts given.

The user message gives the Line, then the facts, each on its own labelled row: Score, Leader, Player total and Event. Decide each of four fields:
- score: every score or standing the line gives (in digits or words, "eighty-five to eighty-six", "three all", "155 for 5", a margin such as "down one", a chase's runs needed) against Score.
- leader: who the line says leads, trails or won, or that it is level, against Leader.
- player_total: the named player's running total the line gives (their points or goals tonight) against Player total.
- event: what the line says just happened (the kind of shot, goal, save, miss, card, foul, four, six, wicket, pit stop, and how it ended) against Event.

For each field answer exactly one label:
- ok: the line states it, and every claim of it matches the fact.
- wrong: the line states it, and any claim of it contradicts the fact.
- not_said: the line makes no claim about it.

Reply with one line of compact JSON and nothing else: the four keys in this order, no spaces, no code fence, no explanation. For example:
{"score":"ok","leader":"not_said","player_total":"not_said","event":"wrong"}

Rules that decide the close cases:
- A scoreline alone ("Chelsea one, Tottenham two", "Lakers 118, Raptors 102") is a score claim only: leader is not_said. Leader is said only by words such as lead, ahead, in front, trail, behind, level, all square, tied, X all, apiece, won, beat, go-ahead, extend the lead, or "X take the lead".
- "two one" or "2-1" with no team order matches Score if those numbers are the score in either order.
- player_total is said only when the line gives the player's own running count ("his 40th point", "her second goal", "a hat-trick", "77 points on the night"). A player scoring with no count is not_said.
- When unsure whether the line states something, answer not_said."""  # noqa: E501

SCHEMA = {
    "type": "object",
    "properties": {f: {"type": "string", "enum": list(LABELS)} for f in FIELDS},
    "required": list(FIELDS),
    "additionalProperties": False,
}

MESSAGE = Template(
    "Line: $line\nSport: $sport\nMatch: $match\nScore: $score\nLeader: $lead\n"
    "Player total: $total\nEvent: $event"
)


def request(message: str, match_id: str, idx: int) -> dict:
    """The one request shape: no tools, the answer held to SCHEMA (the API takes no temperature
    here); 600 tokens because Sonnet thinks before it answers, and 60 left it empty. Mubit sets
    test cases aside by session (user_id), so one session per moment keeps a moment's
    near-identical lines on one side."""
    return {
        "model": MODEL,
        "max_tokens": 600,
        "system": SYSTEM,
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        "metadata": {"user_id": f"line-check-{match_id}-{idx}"},
        "messages": [{"role": "user", "content": message}],
    }


def dumps(label: dict) -> str:
    """The canonical answer: {"score":"ok","leader":"not_said",...}."""
    return json.dumps({f: label[f] for f in FIELDS}, separators=(",", ":"))


def parse(text: str) -> dict | None:
    """The reply as {field: label}, or None unless it is one JSON object of the four fields in
    order (the schema fixes the rest; whitespace aside, that is the canonical line)."""
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(out, dict) or list(out) != list(FIELDS):
        return None
    return out if all(out[f] in LABELS for f in FIELDS) else None
