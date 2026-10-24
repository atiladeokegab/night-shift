"""'Where are we?' (#186): the clock, the score, who leads and what is happening now, in one spoken
line. Its own Mubit task: its own system prompt and no tools, on the commentary's provider, so the
lines' frozen prompt, template and tools stay one task."""

from __future__ import annotations

import logging
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
    _period,
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
    "Sport: $sport\nMatch: $match\nMoment: $period, $clock\nScore: $score\nWho leads: $lead\n"
    "Last event: $type, $outcome ($team; $players)"
)
log = logging.getLogger(__name__)


def _lead(m: dict) -> str:
    """Who leads (#185), or a chase's state; F1's order is in its score."""
    d = m["detail"]
    return d.get("lead") or d.get("chase") or "see the score"


def build_request(header: dict, m: dict) -> dict:
    message = MESSAGE.substitute(
        sport=m["sport"],
        match=_match(header),
        period=_period(m),
        clock=m["clock"],
        score=_score(header, m),
        lead=_lead(m),
        type=m["type"],
        outcome=_outcome(m),  # with the football moment's place (#172)
        team=m["team"],
        players=_players(m),
    )
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "metadata": {"user_id": session_id(header["sport"], header["match_id"])},
        "messages": [{"role": "user", "content": message}],
    }


def fallback_text(header: dict, m: dict) -> str:
    """The status from the moment's data alone: said when the model's numbers stay wrong, or it is
    off air, so "Where are we?" always gets an answer."""
    lead = m["detail"].get("lead") or m["detail"].get("chase")
    said = f"{_period(m)[0].upper()}{_period(m)[1:]}, {m['clock']}. {_score(header, m)}."
    return f"{said} {lead[0].upper()}{lead[1:]}." if lead else said


def status(past: list[dict], header: dict | None = None, provider=None) -> dict:
    """The status at past[-1], the moment on screen: nothing later reaches the request. Checked like
    a moment's line (insight.checked), so a wrong score or leader is never spoken."""
    from core import insight

    m = past[-1]
    if header is None:
        from data.matches import match_header

        header = match_header(m["match_id"])
    provider = provider or default_provider()
    start, replies = time.monotonic(), []

    def say(moment: dict, history: list[dict]) -> dict:
        reply = provider.call(build_request(header, moment))
        replies.append(reply)
        return {
            "text": spoken(
                " ".join(b["text"] for b in reply["content"] if b["type"] == "text"), WORDS
            )
        }

    try:
        out = insight.checked(say, m, past[:-1])
        text = out["text"] if out["text"] and not out.get("fallback") else fallback_text(header, m)
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
