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


# A producer's fix with one of these reasons also teaches Line check (#298); Tone and Other don't
TEACHES = ("Wrong score", "Wrong player", "Wrong fact")


def check(header: dict, m: dict, past: list[dict], text: str, provider) -> dict:
    """The live second opinion (#298) on `text` said over moment m: the seeded request exactly
    (eval/linecheck.py `build_request`), so the call joins the recorded task. `wrong` lists the
    fields it calls wrong; `labels` is None when the reply isn't the one canonical line."""
    from eval.linecheck import build_request

    reply = provider.call(build_request(header, m, past, text))
    labels = parse("".join(b.get("text", "") for b in reply["content"] if b["type"] == "text"))
    return {
        "labels": labels,
        "wrong": [f for f in FIELDS if labels and labels[f] == "wrong"],
        "model": MODEL,
        "tokens_in": reply["usage"]["input_tokens"],
        "tokens_out": reply["usage"]["output_tokens"],
        "mubit_request_id": reply.get("request_id"),
    }


def live_check(line: dict, m: dict, past: list[dict]) -> dict | None:
    """`check` as the replay runs it: recorded as MUBIT_RECORD says, but a held-out match's line
    never, so the test set never trains the adapter. None, and no call, offline (no key)."""
    from agent.commentator import FakeProvider, default_provider, unrecorded_provider
    from data.matches import match_header
    from eval.linecheck import HELD_OUT

    held = line["match_id"] in HELD_OUT
    provider = unrecorded_provider() if held else default_provider()
    if isinstance(provider, FakeProvider):
        return None
    return check(match_header(line["match_id"]), m, past, line["text"], provider)


def teach(line: dict, provider=None) -> dict | None:
    """A producer's fix as one recorded Line check example (#298): the line as first said, its
    moment's facts, and the answer key code gives (eval/linecheck.py `gold`); a reply that
    disagrees gets the correction turn with the key's exact JSON, as the seeding does. None, and
    no call, when code can't decide a field, for a held-out match, a stat line, or no recorder
    (the owner's key, else the lines' provider when it records)."""
    from agent.commentator import correction_provider, default_provider
    from data.matches import load_moments, match_header
    from eval.linecheck import HELD_OUT, example_id, gold
    from eval.seed_linecheck import _go_one

    mid, idx, text = line.get("match_id"), line.get("moment_idx"), line.get("tried") or line["text"]
    if mid in HELD_OUT or line.get("speaker") == "analyst" or "reply" in line or "insight" in line:
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
    key = gold(header, moments[i], moments[:i], text) if i is not None else None
    if key is None:
        return None
    ex = {"id": example_id(mid, idx, text), "match_id": mid, "idx": idx, "text": text, "gold": key}
    ids = []  # each call's Mubit request id: the last is the example, its correction if it has one

    class Seen:
        def call(self, req):
            reply = provider.call(req)
            ids.append(reply.get("request_id"))
            return reply

    kind, _ = _go_one(ex, Seen())  # matched, corrected, uncorrected, leader_only or error
    return {"kind": kind, "gold": dumps(key), "mubit_request_id": ids[-1] if ids else None}
