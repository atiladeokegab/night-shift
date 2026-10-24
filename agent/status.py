"""'Where are we?' (#186): the clock, the score, who leads and what is happening now, in one spoken
line. Its own Mubit task: its own system prompt and no tools, on the commentary's provider, so the
lines' frozen prompt, template and tools stay one task."""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from agent.commentator import (
    MAX_TOKENS,
    MODEL,
    _match,
    _outcome,
    _players,
    _score,
    default_provider,
    session_id,
    spoken,
)

SYSTEM = (Path(__file__).resolve().parent / "status_prompt.md").read_text(encoding="utf-8")
QUESTION = "Where are we?"
WORDS = 25
MESSAGE = Template(
    "Sport: $sport\nMatch: $match\nMoment: $when\nScore: $score\nWho leads: $lead\n"
    "Last event: $type, $outcome ($team; $players)"
)
QUARTERS = ("First", "Second", "Third", "Fourth")
HALVES = {1: "First half", 2: "Second half", 5: "Penalty shootout"}
END = {"Finish", "Full time", "End of game"}  # a match's last moment: whoever leads has won
log = logging.getLogger(__name__)


def _when(m: dict, laps: int | None = None) -> str:
    """The time as a commentator says it: an NBA clock counts down ("First quarter, 0:30 left"),
    a football one is whole minutes played ("Second half, 96 minutes played")."""
    p, clock = m["period"], m["clock"]
    if m["sport"] == "basketball":
        mins, secs = clock.split(":")
        part = f"{QUARTERS[p - 1]} quarter" if p <= 4 else f"Overtime {p - 4}"
        return f"{part}, {int(mins)}:{secs} left"
    if m["sport"] == "football":
        half = HALVES.get(p, "Extra time")
        return half if p == 5 else f"{half}, {int(clock.split(':')[0])} minutes played"
    if m["sport"] == "cricket":
        return f"Innings {p}, over {clock}"
    return f"Lap {p} of {laps}" if laps else f"Lap {p}"


def _people(m: dict) -> str:
    """Who did what. A cricket ball in words, so a catch isn't credited to the bowler: "HH Pandya
    bowling to Shadab Khan; Shadab Khan is out, caught by SA Yadav"."""
    p = m["players"]
    if m["sport"] != "cricket" or not {"batter", "bowler"} <= p.keys():
        return _players(m)
    said = f"{p['bowler']} bowling to {p['batter']}"
    if p.get("out"):
        said += f"; {p['out']} is out, {m['outcome']}"
        said += f" by {p['fielder']}" if p.get("fielder") else ""
    return said


def _crease(m: dict) -> str:
    """The cricket batters at the crease after this ball ("A and B"): not the one just dismissed."""
    p = m["players"]
    return " and ".join(
        n for n in (p.get("batter"), p.get("non_striker")) if n and n != p.get("out")
    )


def _lead(m: dict) -> str:
    """Who leads (#185), a chase's state, F1's P1, or nobody yet in a first innings; at the end,
    who won ("Argentina won the shootout 4-2")."""
    d, s = m["detail"], m["score"]
    if m["sport"] == "cricket" and m["type"] not in END:  # who is in, and what it has cost
        down = f", {s['wickets']} down" if s["wickets"] else ""
        crease = f"; {c} batting" if (c := _crease(m)) else ""
        return f"{_cricket_lead(m, d)}{down}{crease}"
    if d.get("lead") or d.get("chase"):
        lead = d.get("lead") or d["chase"]
    elif s.get("top"):
        lead = f"{min(s['top'], key=lambda c: c['pos'])['driver']} leads"
    elif m["sport"] == "cricket":
        return _cricket_lead(m, d)
    else:
        return "see the score"
    return re.sub(r"\bleads?\b", "won", lead, count=1) if m["type"] in END else lead


def _cricket_lead(m: dict, d: dict) -> str:
    return d.get("lead") or d.get("chase") or f"no one yet, {m['team']} batting first"


def build_request(header: dict, m: dict) -> dict:
    message = MESSAGE.substitute(
        sport=m["sport"],
        match=_match(header),
        when=_when(m, header.get("laps")),
        score=_score(header, m),
        lead=_lead(m),
        type=m["type"],
        outcome=_outcome(m),  # with the football moment's place (#172)
        team=f"{m['team']} batting" if m["sport"] == "cricket" else m["team"],
        players=_people(m),
    )
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "metadata": {"user_id": session_id(header["sport"], header["match_id"])},
        "messages": [{"role": "user", "content": message}],
    }


def fallback_text(header: dict, m: dict) -> str:
    """The status from the moment's data alone: said when the model's line stays wrong, or it is
    off air, so "Where are we?" always gets an answer. The score once: who leads says it."""
    d, s = m["detail"], m["score"]
    if s.get("top"):  # F1: its score line gives the lap
        return f"{_score(header, m)}. {_lead(m)}."
    state = _lead(m) if d.get("lead") else _score(header, m)
    if m["sport"] == "cricket" and m["type"] not in END and (c := _crease(m)):
        state += f". {c} batting"
    if "shootout" in d:  # the shootout's lead alone hides the match score
        return (
            f"{_when(m)}, {s['home']}-{s['away']} after extra time. {state[0].upper()}{state[1:]}."
        )
    return f"{_when(m)}. {state[0].upper()}{state[1:]}."


def says_score(text: str, m: dict) -> bool:
    """The line says the score's numbers (the lap in F1), "one" and "nil" included: the number
    check reads a lone "one" as a word."""
    from core import insight

    s = m["score"]
    if "home" in s:
        need = (s["home"], s["away"])
    else:
        need = (s["runs"], s["wickets"]) if "runs" in s else (s["lap"],)
    words = insight.said(text)
    have = {w for w in words if isinstance(w, float)}
    have |= {1.0} if "one" in words else set()
    have |= {0.0} if {"nil", "nothing", "zero", "love", "none"} & set(words) else set()
    return {float(n) for n in need} <= have


def leads_at_the_end(text: str, m: dict) -> bool:
    """On the last moment, the line still has the winner leading ("Max Verstappen leads") though
    the message says they won. A draw says "level" and is never caught."""
    lead = _lead(m)
    if m["type"] not in END or " won" not in lead:
        return False
    names = [w for w in re.findall(r"[\w'&-]+", lead.split(" won")[0]) if len(w) > 2]
    near = rf"\b(?:{'|'.join(map(re.escape, names))})\b\W+(?:\w+\W+){{0,2}}?lead(?:s|ing)?\b"
    return bool(names) and bool(re.search(near, text, re.I))


def status(past: list[dict], header: dict | None = None, provider=None) -> dict:
    """The status at past[-1], the moment on screen: nothing later reaches the request. Checked like
    a moment's line (insight.wrong_numbers), and it must say the score: tried once more, then the
    status from the data, so a wrong or missing score or leader is never spoken."""
    from core import insight

    m = past[-1]
    if header is None:
        from data.matches import match_header

        header = match_header(m["match_id"])
    provider = provider or default_provider()
    start, replies = time.monotonic(), []

    def right(text: str) -> bool:
        # the status needn't repeat a points milestone; its numbers stay given by player_points
        d = {k: v for k, v in m["detail"].items() if k != "milestone"}
        wrong = insight.wrong_numbers(text, {**m, "detail": d}, header, past[:-1])
        # nor say how the last shot ended: "where are we" is the state, the event is optional
        wrong = [w for w in wrong if not w.startswith("the line never says how the shot ended")]
        # a cricket status names a batter at the crease (the surname will do)
        crease = m["sport"] != "cricket" or m["type"] in END or not (c := _crease(m))
        named = crease or any(n.split()[-1].lower() in text.lower() for n in c.split(" and "))
        return (
            bool(text)
            and says_score(text, m)
            and named
            and not wrong
            and not leads_at_the_end(text, m)
        )

    text = None
    try:
        for _ in range(2):
            reply = provider.call(build_request(header, m))
            replies.append(reply)
            said = spoken(
                " ".join(b["text"] for b in reply["content"] if b["type"] == "text"), WORDS
            )
            if right(said):
                text = said
                break
        text = text or fallback_text(header, m)
    except Exception as exc:  # off air: the data still says where we are
        log.warning("status %s off air: %s: %s", m["match_id"], type(exc).__name__, str(exc)[:300])
        text = fallback_text(header, m)
    return {
        "line_id": uuid.uuid4().hex,  # spoken like an answer: /lines/{id}/audio
        "sport": header["sport"],
        "match_id": header["match_id"],
        "moment_idx": m["idx"],
        "question": QUESTION,
        "text": text,
        "status": True,
        "model": MODEL,
        "latency_ms": round((time.monotonic() - start) * 1000),
        "tokens_in": sum(r["usage"]["input_tokens"] for r in replies),
        "tokens_out": sum(r["usage"]["output_tokens"] for r in replies),
        "mubit_request_ids": [r["request_id"] for r in replies],
        "tool_calls": [],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
