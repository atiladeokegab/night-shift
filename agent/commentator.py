"""The commentator: one frozen prompt, template and tool set for both sports, via Mubit.

Only the moments up to and including the current one ever reach the request or the tools.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from string import Template

AGENT = Path(__file__).resolve().parent
SYSTEM = (AGENT / "prompt.md").read_text(encoding="utf-8")
MESSAGE = (AGENT / "message.md").read_text(encoding="utf-8")
TOOLS = json.loads((AGENT / "tools.json").read_text(encoding="utf-8"))
TOOL_CHOICE = {"type": "auto"}
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 100
MUBIT_URL = "https://api.mubit.ai/anthropic"


def session_id(sport: str, match_id: str) -> str:
    return f"match-{sport}-{match_id}"


def _score(header: dict, m: dict) -> str:
    s = m["score"]
    if m["sport"] == "football":
        text = f"{header['home']} {s['home']}, {header['away']} {s['away']}"
        if "shootout" in m["detail"]:
            so = m["detail"]["shootout"]
            text += f" (penalties {so['home']}-{so['away']})"
        return text
    text = f"{m['team']} {s['runs']}/{s['wickets']}"
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
    if m["sport"] == "cricket":
        return f"innings {m['period']}"
    return "penalty shootout" if m["period"] == 5 else f"period {m['period']}"


def describe(m: dict) -> str:
    return f"{m['clock']} {m['type']}, {m['outcome']} ({m['team']}; {_players(m)})"


def render_message(header: dict, past: list[dict]) -> str:
    m = past[-1]
    recent = [describe(p) for p in past[-4:-1]] or ["none yet"]
    return Template(MESSAGE).substitute(
        sport=m["sport"],
        match=f"{header['home']} v {header['away']}, {header['competition']} {header['stage']}, "
        f"{header['date']}",
        period=_period(m),
        clock=m["clock"],
        type=m["type"],
        outcome=m["outcome"] or "none",
        team=m["team"],
        players=_players(m),
        score=_score(header, m),
        detail=_detail(m),
        recent="\n".join(f"- {r}" for r in recent),
    )


def build_request(header: dict, past: list[dict]) -> dict:
    """The exact production request for the last moment in `past`."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "tools": TOOLS,
        "tool_choice": TOOL_CHOICE,
        "metadata": {"user_id": session_id(header["sport"], header["match_id"])},
        "messages": [{"role": "user", "content": render_message(header, past)}],
    }


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
        return "\n".join(hits[-10:]) or f"No moments yet for {who or 'that player'}."
    if name == "get_recent_play":
        count = (args or {}).get("count", 3)
        count = max(1, min(10, count if isinstance(count, int) else 3))
        return "\n".join(describe(p) for p in past[-count - 1 : -1]) or "No earlier moments."
    return f"Unknown tool {name}."


class NoLine(ValueError):
    """The model gave no usable commentary for a moment."""


# The model talking about its task, not the match: "I have all the information I need ...".
_PREAMBLE = re.compile(
    r"^(?:I\b|I'(?:m|ve|ll|d)\b|Let me\b|Let's (?:see|check|look)\b|Based on\b"
    r"|Here(?:'s| is)\b|(?:Okay|OK|Sure|Great|Alright),)[^.!?:\n]*[.!?:]*\s*"
)


def spoken(text: str) -> str:
    """The line as it should be spoken: leading preamble sentences dropped."""
    text = text.strip()
    while (m := _PREAMBLE.match(text)) and m.end():
        text = text[m.end() :].lstrip()
    return text


def commentate(
    moment: dict, history: list[dict], header: dict | None = None, provider=None
) -> dict:
    """The server's seam: one Line for `moment`, given only the earlier moments."""
    if header is None:
        from data.matches import match_header

        header = match_header(moment["match_id"])
    moments = [*history, moment]
    try:
        return line_for(header, moments, len(history), provider or default_provider())
    except NoLine:
        return None  # the replay skips the moment


CORRECTION = "Producer correction. Reply with exactly this line: {text}"


def correct(
    line: dict, corrected_text: str, header: dict | None = None, moments=None, provider=None
) -> dict:
    """A producer's fix as the next turn of the line's own call: same task, same session."""
    if header is None or moments is None:
        from data.matches import load_moments, match_header

        header = header or match_header(line["match_id"])
        moments = moments if moments is not None else load_moments(line["match_id"])
    request = build_request(header, [m for m in moments if m["idx"] <= line["moment_idx"]])
    request["messages"] += [
        {"role": "assistant", "content": line["text"]},
        {"role": "user", "content": CORRECTION.format(text=corrected_text)},
    ]
    reply = (provider or default_provider()).call(request)
    said = spoken(" ".join(b["text"] for b in reply["content"] if b["type"] == "text"))
    return {"mubit_request_id": reply["request_id"], "reply_matched": said == corrected_text}


_provider = None


def default_provider():
    """Mubit when MUBIT_API_KEY is set, else FakeProvider; made once per process."""
    global _provider
    if _provider is None:
        key = os.environ.get("MUBIT_API_KEY")
        _provider = MubitProvider(key) if key else FakeProvider()
    return _provider


def line_for(header: dict, moments: list[dict], idx: int, provider) -> dict:
    """One Line for moments[idx], with at most one tool round."""
    past = moments[: idx + 1]  # never anything later than this moment
    request = build_request(header, past)
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
    text = spoken(" ".join(b["text"] for b in reply["content"] if b["type"] == "text"))
    if not text:  # a tool-only or preamble-only reply: no line beats a blank or a wrong one
        raise NoLine(f"no commentary for moment {past[-1]['idx']}")
    first = reply.get("first_word_ms")
    return {
        "line_id": uuid.uuid4().hex,
        "sport": header["sport"],
        "match_id": header["match_id"],
        "moment_idx": past[-1]["idx"],
        "text": text,
        "model": MODEL,
        "latency_ms": round((time.monotonic() - start) * 1000),
        "first_word_ms": round(offset + first) if first is not None else None,
        "tokens_in": sum(r["usage"]["input_tokens"] for r in replies),
        "tokens_out": sum(r["usage"]["output_tokens"] for r in replies),
        "mubit_request_ids": [r["request_id"] for r in replies],
        "tool_calls": tool_calls,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _block(b) -> dict:
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return {"type": "text", "text": getattr(b, "text", "")}


class MubitProvider:
    """Anthropic SDK pointed at Mubit; streams so the first word can be timed."""

    def __init__(self, api_key: str, record: bool = True, timeout: float = 20.0):
        import anthropic

        headers = {} if record else {"x-middleware-record": "off"}
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=MUBIT_URL,
            timeout=timeout,
            max_retries=1,
            default_headers=headers,
        )

    def call(self, request: dict) -> dict:
        start, first = time.monotonic(), None
        with self.client.messages.stream(**request) as stream:
            for _ in stream.text_stream:
                if first is None:
                    first = (time.monotonic() - start) * 1000
            msg = stream.get_final_message()
            request_id = stream.response.headers.get("x-middleware-request-id")
        return {
            "content": [_block(b) for b in msg.content],
            "usage": {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            },
            "request_id": request_id,
            "first_word_ms": first,
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
        if isinstance(said, str) and said.startswith("Producer correction"):
            content = [{"type": "text", "text": said.split(": ", 1)[1]}]
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
