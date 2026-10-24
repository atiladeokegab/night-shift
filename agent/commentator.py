"""The commentator: one frozen prompt, template and tool set for every sport, via Mubit.

Only the moments up to and including the current one ever reach the request or the tools.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from core import predict

AGENT = Path(__file__).resolve().parent
SYSTEM = (AGENT / "prompt.md").read_text(encoding="utf-8")
MESSAGE = (AGENT / "message.md").read_text(encoding="utf-8")
ASK = (AGENT / "ask.md").read_text(encoding="utf-8")
ANALYST = (AGENT / "analyst.md").read_text(encoding="utf-8")
TOOLS = json.loads((AGENT / "tools.json").read_text(encoding="utf-8"))
# Ask only: Mubit fingerprints the tools, so a new one in every line would split the lines' task
ASK_TOOLS = TOOLS + json.loads((AGENT / "ask_tools.json").read_text(encoding="utf-8"))
TOOL_CHOICE = {"type": "auto"}
MODEL = "claude-haiku-4-5"
ANALYST_MODEL = (
    "claude-sonnet-5-5"  # the stat lines, unrecorded: Haiku slipped on their facts in probe 7
)
MAX_TOKENS = 100
MUBIT_URL = "https://api.mubit.ai/anthropic"
log = logging.getLogger(__name__)


def session_id(sport: str, match_id: str) -> str:
    return f"match-{sport}-{match_id}"


def _score(header: dict, m: dict) -> str:
    s = m["score"]
    if m["sport"] == "f1":
        return f"Lap {s['lap']} of {s['laps']}: " + ", ".join(
            (f"P{c['pos']} " if c["pos"] else "")
            + c["driver"]
            + (f" {c['gap']}" if c["gap"] else "")
            for c in s["top"]
        )
    if "home" in s:  # football and basketball
        text = f"{header['home']} {s['home']}, {header['away']} {s['away']}"
        if "shootout" in m["detail"]:
            so = m["detail"]["shootout"]
            text += f" (penalties {so['home']}-{so['away']})"
        return text
    text = f"{m['team']} {s['runs']} for {s['wickets']}"  # said as written: runs, then wickets
    if "target" in s:
        need = max(0, s["target"] - s["runs"])
        text += f", target {s['target']}, need {need} from {m['detail']['balls_left']} balls"
    return text


def _players(m: dict) -> str:
    return ", ".join(f"{role}: {name}" for role, name in m["players"].items()) or "none"


def _detail(m: dict) -> str:
    def flat(d):
        return ", ".join(f"{k}: {v}" for k, v in d.items() if v not in ("", None, False, {}, 0))

    return (
        flat({k: flat(v) if isinstance(v, dict) else v for k, v in m["detail"].items()}) or "none"
    )


def _period(m: dict) -> str:
    if m["sport"] == "f1":
        return f"lap {m['period']}"
    if m["sport"] == "cricket":
        return f"innings {m['period']}"
    if m["sport"] == "basketball":
        return f"quarter {m['period']}" if m["period"] <= 4 else f"overtime {m['period'] - 4}"
    return "penalty shootout" if m["period"] == 5 else f"period {m['period']}"


def _outcome(m: dict) -> str:
    """The outcome, with a football moment's place right beside it (#172): left in Details alone,
    the model never said it."""
    where = m["detail"].get("where")
    return (m["outcome"] or "none") + (f", {where}" if where else "")


def describe(m: dict) -> str:
    return f"{m['clock']} {m['type']}, {m['outcome']} ({m['team']}; {_players(m)})"


def _match(header: dict) -> str:
    event = f"{header['competition']} {header['stage']}, {header['date']}"
    return event if header["sport"] == "f1" else f"{header['home']} v {header['away']}, {event}"


def render_message(header: dict, past: list[dict]) -> str:
    m = past[-1]
    recent = [describe(p) for p in past[-4:-1]] or ["none yet"]
    return Template(MESSAGE).substitute(
        sport=m["sport"],
        match=_match(header),
        period=_period(m),
        clock=m["clock"],
        type=m["type"],
        outcome=_outcome(m),
        team=m["team"],
        players=_players(m),
        score=_score(header, m),
        detail=_detail(m),
        recent="\n".join(f"- {r}" for r in recent),
    )


MAX_FIXES = 5  # the request stays small
FIXES = "Producer fixes earlier in this match, to follow from now on:\n{fixes}"
SEEN = "On screen: {seen}"  # what a viewer's shared screen shows (#291, agent/look.py)


def _fixes(past: list[dict], fixes) -> str:
    """The producer's fixes said at or before this moment, newest last: when, the line said, what
    was wrong and the fixed line, each one quoted on one line so it cannot forge a field."""
    at = {m["idx"]: m for m in past}
    kept = [f for f in fixes if f["moment_idx"] in at][-MAX_FIXES:]  # never a later moment's
    return "\n".join(
        f"- {_period(at[f['moment_idx']])}, {at[f['moment_idx']]['clock']}: you said "
        f"{json.dumps(f['said'], ensure_ascii=False)}"
        + (f" ({json.dumps(f['reason'][:200], ensure_ascii=False)})" if f.get("reason") else "")
        + f"; the producer's line: {json.dumps(f['fixed'], ensure_ascii=False)}"
        for f in kept
    )


def fix_context(line: dict) -> dict:
    """What a fix to `line` carries into later requests, stamped on the fix row when it is posted,
    so a line's request reads only "fixes"."""
    return {
        "match_id": line.get("match_id"),
        "moment_idx": line.get("moment_idx"),
        # a line built from the data was spoken in place of a failed try: that try, and why
        "said": line.get("tried") or line.get("text") or "",
        "wrong": line.get("wrong") or [],
    }


def match_fixes(store, match_id: str, known: dict | None = None) -> list[dict]:
    """This match's stored producer fixes, oldest first and the newest per line, as `build_request`
    takes them. A fix stored before rows were stamped is resolved from "lines" once and kept in
    `known` by line id (a line never changes), so later calls read only "fixes"."""
    known = {} if known is None else known
    fixes = store.all("fixes")
    if old := {f.get("line_id") for f in fixes if "match_id" not in f} - known.keys():
        lines = {ln.get("line_id"): ln for ln in store.all("lines") if ln.get("line_id") in old}
        known.update({i: fix_context(lines[i]) if i in lines else None for i in old})
    out: dict[str, dict] = {}
    for f in fixes:
        at = f if "match_id" in f else known.get(f.get("line_id"))
        if not at or at["match_id"] != match_id or at["moment_idx"] is None:
            continue
        out.pop(f["line_id"], None)  # a later fix to the same line replaces it, and moves last
        out[f["line_id"]] = {
            "moment_idx": at["moment_idx"],
            "said": at["said"],
            "reason": "; ".join(at.get("wrong") or []) or f.get("reason") or "",
            "fixed": f["corrected_text"],
        }
    return list(out.values())


def build_request(header: dict, past: list[dict], fixes=(), seen: str | None = None) -> dict:
    """The exact production request for the last moment in `past`. A Stat moment (an insight or
    reply, core/insight.py) gets the analyst's own prompt and no tools: it is never recorded, so
    the frozen prompt and tools the lines train on stay one task. `fixes`, the match's stored
    producer fixes ({moment_idx, said, reason, fixed}), go in the user message, never the system
    prompt, so the Mubit task stays the same; none leaves the request as it was. `seen`, a note of
    the viewer's shared screen (#291), goes there too, after them."""
    request = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "tools": TOOLS,
        "tool_choice": TOOL_CHOICE,
        "metadata": {"user_id": session_id(header["sport"], header["match_id"])},
        "messages": [{"role": "user", "content": render_message(header, past)}],
    }
    if said := _fixes(past, fixes):
        request["messages"][0]["content"] += "\n" + FIXES.format(fixes=said)
    if seen:
        request["messages"][0]["content"] += "\n" + SEEN.format(seen=seen)
    if past[-1]["type"] == "Stat":
        request["system"] = ANALYST
        # unrecorded, so its model is free to differ from the lines' (one Mubit task)
        request["model"] = os.environ.get("ANALYST_MODEL") or ANALYST_MODEL
        del request["tools"], request["tool_choice"]
        if request["model"] == "claude-sonnet-5-5":
            # its lowest thinking setting, so thinking can't eat MAX_TOKENS; other models 400 on it
            request["thinking"] = {"type": "between_tools"}
    return request


def run_tool(name: str, args: dict, header: dict, past: list[dict]) -> str:
    m = past[-1]
    if name == "get_score":
        return f"{_score(header, m)}; {_period(m)}, {m['clock']}"
    if name == "get_player":
        who = str((args or {}).get("name", "")).strip().lower()
        hits = [
            describe(p)
            for p in past
            if who and any(who in n.lower() for n in p["players"].values())
        ]
        # never echo the name: it came through the model from a viewer and could forge a field
        return "\n".join(hits[-10:]) or "No moments yet for that player."
    if name == "get_recent_play":
        count = (args or {}).get("count", 3)
        count = max(1, min(10, count if isinstance(count, int) else 3))
        return "\n".join(describe(p) for p in past[-count - 1 : -1]) or "No earlier moments."
    if name in ("get_player_profile", "get_next_score_odds"):
        pack = predict.load_pack(header["sport"], header["match_id"])
        if pack is None:
            return "No pre-match record for this event."
        if name == "get_next_score_odds":
            return predict.odds_text(pack, past, len(past) - 1)
        return predict.profile_text(pack, past, len(past) - 1, str((args or {}).get("name", "")))
    return f"Unknown tool {name}."


class NoLine(ValueError):
    """The model gave no usable commentary for a moment."""


# The model talking about its task, not the match: "I have all the information I need ...".
_PREAMBLE = re.compile(
    r"^(?:I\b|I'(?:m|ve|ll|d)\b|Let me\b|Let's (?:see|check|look)\b|Based on\b"
    r"|Here(?:'s| is)\b|(?:Okay|OK|Sure|Great|Alright),)[^.!?:…\n]*[.!?:…]*\s*"
)


# A stray grade word the model put before the line: "BAD Manenti with a boundary!".
_STRAY = re.compile(r"^BAD\s+(?=[A-Z])")
MAX_WORDS = 20
ANALYST_WORDS = 25  # a stat line needs room for its numbers

# The model questioning its input instead of calling the moment: "There's a discrepancy here ...".
_META = re.compile(
    r"\b(?:your message|the message|you say|you said|could you|clarify|discrepancy|the tools?"
    r"|labell?ed as|the score confirms)\b",
    re.I,
)


def spoken(text: str, limit: int = MAX_WORDS) -> str:
    """The line as spoken: preamble dropped, and any paragraph about the input left out."""
    kept = []
    for para in re.split(r"\n\s*\n", text.strip()):
        para = para.strip()
        while (m := _PREAMBLE.match(para)) and m.end():
            para = para[m.end() :].lstrip()
        para = _STRAY.sub("", para)
        if para and not _META.search(para):
            kept.append(para)
    return _fit(" ".join(kept), limit)


def _fit(text: str, limit: int = MAX_WORDS) -> str:
    """The whole line, else its first and last sentences (the score usually closes it), else the
    first sentence; one long first sentence is no line."""
    # a sentence ends at punctuation before a space, so "19.4 overs" stays whole
    s = re.split(r"(?<=[.!?…])\s+", text.strip())
    for out in (s, s[:1] + s[-1:], s[:1]):
        if len(" ".join(out).split()) <= limit:
            return " ".join(out)
    return ""


def commentate(
    moment: dict,
    history: list[dict],
    header: dict | None = None,
    provider=None,
    fixes=(),
    seen: str | None = None,
) -> dict:
    """The server's seam: one Line for `moment`, given only the earlier moments and the match's
    producer fixes (`build_request`). A line made with `seen`, what a viewer's shared tab showed, is
    untrusted (#291): called unrecorded, so never training data, and marked `screen`, so it goes
    only to that viewer."""
    if header is None:
        from data.matches import match_header

        header = match_header(moment["match_id"])
    moments = [*history, moment]
    if provider is None:
        provider = unrecorded_provider() if seen else provider_for(moment)
    try:
        line = line_for(header, moments, len(history), provider, fixes, seen)
    except NoLine:
        return None  # the replay skips the moment
    return {**line, "screen": True} if seen and line else line


# the line check's seeding (eval/seed_linecheck.py): its answer is one exact JSON line, so an echo
CORRECTION = "Producer correction. Reply with exactly this line: {text}"

# A producer's fix (#245): what was wrong and the facts, so the recorded example is a wrong call
# corrected, not a line copied
FIX = Template(
    "Producer correction: $reason\n"
    "The facts at this moment. Score: $score. Leader: $lead. Player total: $total.\n"
    "The producer's line: $fixed\n"
    "Say your line again, corrected: the line alone, at most $words words."
)


def correction_turn(header: dict, past: list[dict], corrected_text: str, reason: str = "") -> str:
    """The user turn a fix sends after the line it corrects: the reason, the facts the number
    check reads, and the producer's text as the reference."""
    from agent.status import _lead
    from data.matches import _lead as _score_lead
    from eval.linecheck import player_total

    m = past[-1]
    # a Stat moment keeps none of its moment's detail, so who leads comes from that moment
    said_at = past[-2] if m["type"] == "Stat" and len(past) > 1 else m
    total = player_total(m, past[:-1]) if m["type"] != "Stat" else None
    unit = ("point" if m["sport"] == "basketball" else "goal") + "s" * bool(total and total[1] != 1)
    lead = _lead(said_at)
    if lead == "see the score":  # no lead in the data: who leads by the score, or level
        lead = _score_lead(header, said_at)
    return FIX.substitute(
        # one line each: a line break in either must not forge a field the model reads
        reason=" ".join(reason.split()) or "the line is wrong.",
        score=_score(header, m),
        lead=lead[0].upper() + lead[1:],
        total=f"{total[0]}, {total[1]:g} {unit} tonight" if total else "none",
        fixed=" ".join(corrected_text.split()),
        words=ANALYST_WORDS if m["type"] == "Stat" else MAX_WORDS,
    )


def correct(
    line: dict,
    corrected_text: str,
    header: dict | None = None,
    moments=None,
    provider=None,
    reason: str = "",
) -> dict:
    """A producer's fix as the next turn of the line's own call: same task, same session. Only
    the messages differ from the line's request. It goes unrecorded first (`provider`, else
    `unrecorded_provider()`); only a reply that passes the number check is sent again, the same
    request, on the recording provider. A reply that fails it is not resent."""
    from core.insight import wrong_numbers
    from core.review import UNSAID

    if header is None or moments is None:
        from data.matches import load_moments, match_header

        header = header or match_header(line["match_id"])
        moments = moments if moments is not None else load_moments(line["match_id"])
    past = [m for m in moments if m["idx"] <= line["moment_idx"]]
    request = build_request(header, past)
    turn = correction_turn(header, past, corrected_text, reason)
    request["messages"] += [
        {"role": "assistant", "content": line["text"]},
        {"role": "user", "content": turn},
    ]
    limit = ANALYST_WORDS if past[-1]["type"] == "Stat" else MAX_WORDS

    def ask(p) -> tuple[dict, str, bool]:
        reply = p.call(copy.deepcopy(request))
        said = spoken(" ".join(b["text"] for b in reply["content"] if b["type"] == "text"), limit)
        # the number check a fix itself passes (#232): a reply that fails it is no correction
        wrong = [w for w in wrong_numbers(said, past[-1], header, past[:-1]) if UNSAID not in w]
        return reply, said, bool(said) and not wrong

    reply, said, passed = ask(provider or unrecorded_provider())
    trainer = None
    if passed and past[-1]["type"] != "Stat":  # a Stat's fix stays unrecorded, like its line
        # the owner's key; without one, the lines' own provider when it records
        trainer = correction_provider() or (
            default_provider() if getattr(default_provider(), "record", False) else None
        )
    if trainer is not None:
        reply, said, passed = ask(trainer)  # the recorded example: its own reply, checked again
    return {
        "mubit_request_id": reply.get("request_id"),  # None when the provider gives none
        "correction": turn,  # exactly what Mubit was given after the line
        "reply": said,
        "reply_passed": passed,
        # True only when Mubit recorded it for training: never a reply that failed the check first
        "recorded": getattr(trainer, "record", False),
    }


_provider = None


def default_provider():
    """Mubit when MUBIT_API_KEY is set, else FakeProvider; made once per process."""
    global _provider
    if _provider is None:
        key = os.environ.get("MUBIT_API_KEY")
        # MUBIT_RECORD=off: the key's app pays for lines but trains on none (a lent demo key)
        record = os.environ.get("MUBIT_RECORD", "on") != "off"
        # the owner's key, used once the lent one runs out (402): the owner's app trains on it
        owner = os.environ.get("MUBIT_FALLBACK_KEY")
        fallback = MubitProvider(owner) if owner else None
        _provider = MubitProvider(key, record=record, fallback=fallback) if key else FakeProvider()
    return _provider


_trainer = None


def correction_provider():
    """Mubit on the owner's key, recorded whatever MUBIT_RECORD says: a producer's fix is the
    example the owner's app trains on, and the lent key never records. None without an owner key."""
    global _trainer
    owner = os.environ.get("MUBIT_FALLBACK_KEY")
    if _trainer is None and owner:
        _trainer = MubitProvider(owner, record=True)
    return _trainer


_unrecorded = None


def provider_for(moment: dict):
    """The analyst's Stat lines go unrecorded, like Ask; every moment's line is recorded."""
    return unrecorded_provider() if moment["type"] == "Stat" else default_provider()


def unrecorded_provider():
    """Mubit with recording off when MUBIT_API_KEY is set, else FakeProvider; made once per process.
    An answer has its own system prompt: recorded, it would split the one task the lines train."""
    global _unrecorded
    if _unrecorded is None:
        key = os.environ.get("MUBIT_API_KEY")
        owner = os.environ.get("MUBIT_FALLBACK_KEY")
        fallback = MubitProvider(owner, record=False) if owner else None
        _unrecorded = MubitProvider(key, record=False, fallback=fallback) if key else FakeProvider()
    return _unrecorded


def line_for(
    header: dict, moments: list[dict], idx: int, provider, fixes=(), seen: str | None = None
) -> dict:
    """One Line for moments[idx], with at most one tool round."""
    past = moments[: idx + 1]  # never anything later than this moment
    start = time.monotonic()
    request = build_request(header, past, fixes, seen)
    reply, replies, tool_calls, offset = _call(provider, request, header, past)
    limit = ANALYST_WORDS if past[-1]["type"] == "Stat" else MAX_WORDS
    text = spoken(" ".join(b["text"] for b in reply["content"] if b["type"] == "text"), limit)
    if not text:  # a tool-only or preamble-only reply: no line beats a blank or a wrong one
        raise NoLine(f"no commentary for moment {past[-1]['idx']}")
    first = reply.get("first_word_ms")
    return {
        "line_id": uuid.uuid4().hex,
        "sport": header["sport"],
        "match_id": header["match_id"],
        "moment_idx": past[-1]["idx"],
        "text": text,
        "model": request["model"],
        "served_by": reply.get("served_by"),  # None from FakeProvider: nothing answered
        "latency_ms": round((time.monotonic() - start) * 1000),
        "first_word_ms": round(offset + first) if first is not None else None,
        "tokens_in": sum(r["usage"]["input_tokens"] for r in replies),
        "tokens_out": sum(r["usage"]["output_tokens"] for r in replies),
        "mubit_request_ids": [r["request_id"] for r in replies],
        "tool_calls": tool_calls,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


ANSWER_WORDS = 30
QUESTION = "Lines said so far:\n{lines}\nViewer question: {question}"
# football's period as said: "period 3" read as the second half of extra time on prod (#236)
PARTS = {
    1: "first half",
    2: "second half",
    3: "first half of extra time",
    4: "second half of extra time",
    5: "penalty shootout",
}


def goals_so_far(past: list[dict]) -> list[dict]:
    """Every goal up to the moment on screen, shootout kicks left out."""
    return [
        p
        for p in past
        if (p.get("type"), p.get("outcome")) == ("Shot", "Goal")
        and "shootout" not in (p.get("detail") or {})
    ]


def _goals(past: list[dict]) -> list[dict]:
    """Every goal so far, own goals too, in order: Ask's score must add up (#319)."""
    shots = {id(p) for p in goals_so_far(past)}
    return [p for p in past if id(p) in shots or p.get("outcome") == "Own goal"]


def _goal(header: dict, p: dict) -> str:
    if p["outcome"] == "Own goal":
        other = header["away"] if p["team"] == header["home"] else header["home"]
        return f"- {p['clock']} {p['players'].get('scorer')} ({p['team']}), own goal for {other}"
    shot = p["detail"].get("shot_type", "goal").lower()
    return f"- {p['clock']} {p['players'].get('shooter')} ({p['team']}), {shot}"


def _counted(n: int, thing: str) -> str:
    return f"{n} {thing}{'s' * (n != 1)}"


def _tally(header: dict, past: list[dict]) -> str:
    """The counts a judge asks for and the recent play can't give (#319): each side's shots and
    cards and each scorer's goals, or a basketball player's points at their latest basket here and
    the clock as time left."""
    from agent.status import _when

    m = past[-1]
    if m["sport"] == "basketball":
        points: dict[str, tuple[int, str]] = {}
        for p in past:
            if (who := p["players"].get("shooter")) and p["detail"].get("player_points"):
                points[who] = (p["detail"]["player_points"], _when(p))
        said = sorted(points.items(), key=lambda kv: -kv[1][0])
        return (
            f"\nClock: {_when(m)}"
            + "\nPoints, as of each player's latest basket so far: "
            + ("; ".join(f"{who} {n} ({at})" for who, (n, at) in said) or "none yet")
        )
    if m["sport"] != "football":
        return ""
    sides = (header["home"], header["away"])
    shots = [p["team"] for p in past if p["type"] == "Shot" and "shootout" not in p["detail"]]
    cards = [p for p in past if (p["detail"] or {}).get("card")]
    scorers: dict[str, int] = {}
    for p in goals_so_far(past):
        who = p["players"].get("shooter")
        scorers[who] = scorers.get(who, 0) + 1

    def side_cards(team: str) -> str:
        kinds = [p["detail"]["card"].lower() for p in cards if p["team"] == team]
        return ", ".join(_counted(kinds.count(k), k) for k in dict.fromkeys(kinds)) or "none"

    return (
        "\nShots so far (not shootout kicks): "
        + ", ".join(f"{t} {shots.count(t)}" for t in sides)
        + "\nCards so far: "
        + "; ".join(f"{t} {side_cards(t)}" for t in sides)
        + "\nGoals by player: "
        + (", ".join(f"{who} {_counted(n, 'goal')}" for who, n in scorers.items()) or "none yet")
    )


def answer(
    question: str,
    past: list[dict],
    lines: list[dict],
    header: dict | None = None,
    provider=None,
    wrong: list[str] = (),
) -> dict:
    """A viewer's question about the match so far, answered in the same Mubit session. `past` ends
    at the moment on screen: the request and the tools never see a later one. `wrong` is the check's
    reasons for the last answer, when this is the one retry."""
    if header is None:
        from data.matches import match_header

        header = match_header(past[-1]["match_id"])
    request = build_request(header, past)
    request["system"] = ASK
    request["tools"] = ASK_TOOLS
    heard = "\n".join(f"- {ln['text']}" for ln in lines[-5:]) or "- none yet"
    # one quoted line: a line break in the question must not forge a field the model reads
    quoted = json.dumps(" ".join(question.split()), ensure_ascii=False)
    # the message's recent play is three moments: a goal before them was missing (#236)
    if past[-1]["sport"] == "football":
        request["messages"][0]["content"] += (
            f"\nPart of the match: {PARTS[past[-1]['period']]}"
            + "\nGoals so far:\n"
            + ("\n".join(_goal(header, p) for p in _goals(past)) or "- none yet")
        )
    request["messages"][0]["content"] += _tally(header, past)
    request["messages"][0]["content"] += "\n" + QUESTION.format(lines=heard, question=quoted)
    if wrong:
        request["messages"][0]["content"] += (
            "\nYour last answer was wrong: " + "; ".join(wrong) + ". Answer from the message."
        )
    start = time.monotonic()
    reply, replies, tool_calls, _ = _call(provider or unrecorded_provider(), request, header, past)
    said = " ".join(b["text"] for b in reply["content"] if b["type"] == "text")
    text = spoken(said, ANSWER_WORDS)
    if not text:
        raise NoLine(f"no answer at moment {past[-1]['idx']}")
    return {
        "line_id": uuid.uuid4().hex,  # an answer is spoken like a line: /lines/{id}/audio
        "sport": header["sport"],
        "match_id": header["match_id"],
        "moment_idx": past[-1]["idx"],
        "question": question,
        "text": text,
        "model": MODEL,
        "latency_ms": round((time.monotonic() - start) * 1000),
        "tokens_in": sum(r["usage"]["input_tokens"] for r in replies),
        "tokens_out": sum(r["usage"]["output_tokens"] for r in replies),
        "mubit_request_ids": [r["request_id"] for r in replies],
        "tool_calls": tool_calls,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _call(provider, request: dict, header: dict, past: list[dict]):
    """The reply to `request`, with at most one tool round answered from `past` only."""
    start = time.monotonic()
    reply = provider.call(request)
    replies, tool_calls, offset = [reply], [], 0.0
    uses = [b for b in reply["content"] if b["type"] == "tool_use"]
    if uses:
        results = []
        for b in uses:
            out = run_tool(b["name"], b["input"], header, past)
            tool_calls.append({"name": b["name"], "input": b["input"], "output": out})
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": out})
        request = {
            **request,
            "messages": request["messages"]
            + [
                {"role": "assistant", "content": reply["content"]},
                {"role": "user", "content": results},
            ],
        }
        offset = (time.monotonic() - start) * 1000
        reply = provider.call(request)  # the last round: any further tool request is dropped
        replies.append(reply)
    return reply, replies, tool_calls, offset


def _block(b) -> dict:
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return {"type": "text", "text": getattr(b, "text", "")}


class MubitProvider:
    """Anthropic SDK pointed at Mubit; streams so the first word can be timed. A key that runs out
    of credit (402) hands every later call to `fallback`'s key."""

    def __init__(self, api_key: str, record: bool = True, timeout: float = 20.0, fallback=None):
        import anthropic

        self.fallback = fallback
        self.record = record

        headers = {} if record else {"x-middleware-record": "off"}
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=MUBIT_URL,
            timeout=timeout,
            max_retries=1,
            default_headers=headers,
        )

    def call(self, request: dict) -> dict:
        import anthropic

        client, start = self.client, time.monotonic()
        try:
            return self._stream(client, request)
        except anthropic.APIStatusError as exc:
            if exc.status_code != 402 or not self.fallback or client is self.fallback.client:
                raise
            failed_ms = (time.monotonic() - start) * 1000
            if self.client is client:  # once, even when two replays hit the 402 together
                log.warning(
                    "mubit: the key ran out of credit (402); switching to MUBIT_FALLBACK_KEY"
                )
                self.client = self.fallback.client  # sticky: no failed call before every line
                self.record = self.fallback.record
            reply = self.fallback.call(request)
            if reply["first_word_ms"] is not None:  # the viewer waited through the 402 as well
                reply["first_word_ms"] += failed_ms
            return reply

    def _stream(self, client, request: dict) -> dict:
        start, first = time.monotonic(), None
        with client.messages.stream(**request) as stream:
            for _ in stream.text_stream:
                if first is None:
                    first = (time.monotonic() - start) * 1000
            msg = stream.get_final_message()
            headers = stream.response.headers
        middleware = {k: v for k, v in headers.items() if k.lower().startswith("x-middleware-")}
        return {
            "content": [_block(b) for b in msg.content],
            "usage": {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            },
            "request_id": middleware.get("x-middleware-request-id"),
            "first_word_ms": first,
            # whatever model Mubit's reply names, as it names it (#250)
            "served_by": msg.model,
            "middleware": middleware,
        }


class FakeProvider:
    """Offline stand-in: asks get_score once on a goal or wicket, then reads the event back."""

    def __init__(self):
        self.requests: list[dict] = []

    def call(self, request: dict) -> dict:
        self.requests.append(copy.deepcopy(request))
        n = len(self.requests)
        msgs = request["messages"]
        text = msgs[0]["content"]
        fields = dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)
        big = fields.get("Event", "").startswith(("Shot, Goal", "Wicket"))
        said = msgs[-1]["content"]
        asked = "\nViewer question: " in text
        if isinstance(said, str) and said.startswith("Producer correction. Reply with exactly"):
            content = [{"type": "text", "text": said.split(": ", 1)[1]}]
        elif isinstance(said, str) and said.startswith("Producer correction: "):
            # a fix (#245): the producer's line, said as the corrected line
            fixed = re.search(r"^The producer's line: (.*)$", said, re.M)[1]
            content = [{"type": "text", "text": fixed}]
        elif "Who leads" in fields:  # "Where are we?" (agent/status.py): the data read back
            lead, score = fields["Who leads"], fields["Score"]
            # a lead that holds every number of the score says it: "Level at 70-70", not both
            if set(re.findall(r"\d+", score)) <= set(re.findall(r"\d+", lead)):
                text = f"{fields['Moment']}. {lead[0].upper()}{lead[1:]}."
            else:
                text = f"{fields['Moment']}. {score}. {lead[0].upper()}{lead[1:]}."
            content = [{"type": "text", "text": text}]
        elif asked:  # a viewer's question: the score in the request, so a spoiler would show
            score = fields.get("Score after this moment")
            content = [{"type": "text", "text": f"So far, {score}."}]
        elif len(msgs) == 1 and big:
            content = [
                {"type": "tool_use", "id": f"fake-tool-{n}", "name": "get_score", "input": {}}
            ]
        else:
            content = [{"type": "text", "text": f"{fields.get('Event')} for {fields.get('Team')}!"}]
        return {
            "content": content,
            "usage": {"input_tokens": len(json.dumps(request)) // 4, "output_tokens": 12},
            "request_id": f"fake-{n}",
            "first_word_ms": 1.0,
        }
