"""Talk to the commentator (#380): the fan speaks with the commentator in the browser through an
ElevenLabs agent. The page gets a signed URL from GET /converse/{sport}/{match_id}/token (the API
key stays here); the agent's custom LLM is POST /converse/v1/chat/completions, which answers each
turn through the Ask path (Claude via Mubit, unrecorded) from the match cut at the moment the
conversation started."""

import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent import commentator
from core import insight
from core.guard import OFF_TODAY, client_ip
from core.replay import OFF_AIR

log = logging.getLogger("touchline.converse")
SIGNED_URL = "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"
CTX_TTL_S = 30 * 60  # a conversation's context lives this long after it is minted
MAX_TURNS = 40  # model calls one conversation may make
ASKED_CHARS = 200  # as long as an Ask question
BEFORE_CHARS = 150  # of the commentator's last words, carried into the next question
CTX = re.compile(r"ctx=([A-Za-z0-9_-]{20,})")


async def signed_url(agent_id: str, key: str) -> str:
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.get(
            SIGNED_URL, params={"agent_id": agent_id}, headers={"xi-api-key": key}
        )
        resp.raise_for_status()
        return resp.json()["signed_url"]


def words(content) -> str:
    """A message's text: a string, or the text parts of a list."""
    if isinstance(content, list):
        content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return " ".join(str(content or "").split())


def question_of(messages: list[dict]) -> str:
    """The fan's last words, with the commentator's last reply before them so "and how far out?"
    still has its subject."""
    said = [(m.get("role"), words(m.get("content"))) for m in messages]
    users = [i for i, (role, text) in enumerate(said) if role == "user" and text]
    if not users:
        return ""
    question = said[users[-1]][1][:ASKED_CHARS]
    before = next((t for r, t in reversed(said[: users[-1]]) if r == "assistant" and t), "")
    return f"{question} (you had just said: {before[:BEFORE_CHARS]})" if before else question


class Stopped(Exception):
    """The answer was cut while the model was still writing it, after using `tokens` (in, out)."""

    def __init__(self, tokens: tuple[int, int]):
        super().__init__("answer cut")
        self.tokens = tokens


class Tap:
    """A provider that hands each piece of text to `on_text` as the model writes it, and `on_tool`
    when it asks for a tool, then returns the whole reply as the Ask path expects. One without a
    streaming client (the offline FakeProvider) gives its text in one piece when done. Setting
    `stop` ends the stream at its next event, with Stopped."""

    def __init__(self, inner, on_text, on_tool, on_tools=lambda outputs: None):
        self.inner, self.on_text, self.on_tool, self.on_tools = inner, on_text, on_tool, on_tools
        self.stop, self.tokens = threading.Event(), (0, 0)  # the finished rounds' (in, out)

    def call(self, request: dict) -> dict:
        msgs = request.get("messages") or []
        last = msgs[-1].get("content") if msgs else None
        if isinstance(last, list) and (
            done := [
                b["content"] for b in last if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
        ):
            self.on_tools(done)  # the final round: its sentences are checked against these
        client = getattr(self.inner, "client", None)
        if not hasattr(getattr(client, "messages", None), "stream"):
            reply = self.inner.call(request)
            self.on_text(" ".join(b["text"] for b in reply["content"] if b["type"] == "text"))
            return reply
        with client.messages.stream(**request) as stream:
            for event in stream:
                if self.stop.is_set():  # leaving the block closes the stream: no more tokens
                    # shortcut: output tokens are the snapshot's, set at the round's start and end,
                    # so a cut round's few output tokens go uncounted; its input tokens count
                    now = getattr(stream, "current_message_snapshot", None)
                    used = getattr(now, "usage", None)
                    raise Stopped(
                        (
                            self.tokens[0] + getattr(used, "input_tokens", 0),
                            self.tokens[1] + getattr(used, "output_tokens", 0),
                        )
                    )
                if event.type == "text":
                    self.on_text(event.text)
                elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                    self.on_tool()
            msg = stream.get_final_message()
            self.tokens = (
                self.tokens[0] + msg.usage.input_tokens,
                self.tokens[1] + msg.usage.output_tokens,
            )
            headers = getattr(getattr(stream, "response", None), "headers", {})
        request_id = next(
            (value for key, value in headers.items() if key.lower() == "x-middleware-request-id"),
            None,
        )
        return {
            "content": [commentator._block(b) for b in msg.content],
            "usage": {
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            },
            "request_id": request_id,
        }


# The model saying the question back about "the viewer": spoken() only drops an echo ending in "?"
ABOUT_VIEWER = re.compile(r"^(?:So )?[Tt]he (?:viewer|fan|user)\b")
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def checked(answer: dict, question: str, past: list[dict], lines: list[dict]) -> bool:
    """Ask's number and claim checks on a sentence or completed answer."""
    text = answer["text"]
    return not (
        insight.wrong_answer(answer, question, past, lines)
        + insight.wrong_claims(text, past, question)
        + insight.wrong_lead_move(text, past)
    )


def fail(reason: str, exc: BaseException) -> None:
    """One line per error: what failed and its type, never the key, the prompt or the message."""
    log.warning("converse: %s: %s", reason, type(exc).__name__)


def safe_line(past: list[dict]) -> str:
    """The status line from the data alone, as Ask falls back to; the off-air line without it."""
    from agent.status import fallback_text
    from data.matches import match_header

    try:
        return fallback_text(match_header(past[-1]["match_id"]), past[-1])
    except Exception as exc:
        fail("status line", exc)
        return OFF_AIR


def counted(ask, record):
    """`ask` that hands each answer it makes (a model call's cost) to `record`, and the cost of one
    cut while the model was writing it."""

    def call(*args, **kwargs):
        try:
            made = ask(*args, **kwargs)
        except Stopped as cut:
            tokens_in, tokens_out = cut.tokens
            record(
                {
                    "model": commentator.MODEL,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "cut": True,
                }
            )
            raise
        if made:
            record(made)
        return made

    return call


async def speak(ask, inner, question: str, past: list[dict], lines: list[dict]):
    """The answer's sentences, each as soon as the model has written it and Ask's checks pass it.
    A sentence that fails stops the answer there; if nothing was said yet (or a tool was used, so
    the checks need its output) the whole answer goes through `insight.checked_answer`. A cut
    answer stops the model writing the rest."""
    loop = asyncio.get_running_loop()
    pieces = asyncio.Queue()

    def put(kind, value=None):
        loop.call_soon_threadsafe(pieces.put_nowait, (kind, value))

    tap = Tap(inner, lambda t: put("text", t), lambda: put("tool"), lambda o: put("tools", o))

    def work():
        try:
            return ask(question, past, lines, provider=tap)
        finally:
            put("end")

    task = asyncio.create_task(asyncio.to_thread(work))
    task.add_done_callback(
        lambda t: (
            t.cancelled()
            or t.exception()
            and not isinstance(t.exception(), Stopped)
            and fail("model call", t.exception())
        )
    )
    buf, said, words_left, tooled, failed = "", [], commentator.ANSWER_WORDS, False, False
    outputs: list = []
    try:  # a cut answer, a failed check or a fan who hung up: the model stops writing
        while not failed:
            kind, value = await pieces.get()
            if kind == "tool":
                tooled = True  # a tool round: nothing is said until its outputs are known
            elif kind == "tools":
                # the final round streams, checked against them
                tooled, outputs, buf = False, value, ""
            elif kind == "text":
                buf += value
            ready = SENTENCE.split(buf)
            if kind == "end":
                ready, buf = [r for r in ready if r.strip()], ""
            else:
                buf = ready.pop()  # the sentence still being written
            for sentence in ready if not tooled else []:
                heard = commentator.spoken(sentence, words_left, ask=True)
                if not heard or ABOUT_VIEWER.match(heard):
                    continue
                one = {"text": heard, "tool_calls": [{"output": o} for o in outputs]}
                if not checked(one, question, past, lines):
                    log.warning("converse: a sentence failed the number check")
                    failed = True
                    break
                words_left -= len(heard.split())
                said.append(heard)
                yield heard
                if words_left <= 0:
                    failed = True  # the answer's length: the rest is not said
                    break
            if kind == "end":
                break
    finally:
        tap.stop.set()
    if said:
        return
    # nothing was said. A tool round held its sentences back (the checks need the tool's output):
    # the answer that call chain already made is checked whole and said, with no second model call
    try:
        made = await task
    except Exception:  # logged by the done-callback
        made = None
    if made and checked(made, question, past, lines):
        yield made["text"]
        return
    # no text event we know, a failed answer or call: Ask's own path, so the fan is never in silence
    try:
        safe = await asyncio.to_thread(insight.checked_answer, ask, question, past, lines)
    except Exception as exc:  # the status line, never the provider's error
        fail("answer", exc)
        yield safe_line(past)
        return
    yield safe["text"] if safe else safe_line(past)


def chunk(cid: str, delta: dict, finish: str | None = None) -> str:
    body = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "touchline",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body)}\n\n"


def sse(text: str):
    cid = f"chatcmpl-{uuid.uuid4().hex}"
    yield chunk(cid, {"role": "assistant"})
    parts = text.split(" ")  # word by word, each with the space after it, so speech starts at once
    for i, part in enumerate(parts):
        yield chunk(cid, {"content": part + (" " if i < len(parts) - 1 else "")})
    yield chunk(cid, {}, "stop")
    yield "data: [DONE]\n\n"


async def sse_of(sentences):
    """The chat.completion.chunk stream for sentences as they come."""
    cid = f"chatcmpl-{uuid.uuid4().hex}"
    yield chunk(cid, {"role": "assistant"})
    first = True
    async for sentence in sentences:
        yield chunk(cid, {"content": ("" if first else " ") + sentence})
        first = False
    yield chunk(cid, {}, "stop")
    yield "data: [DONE]\n\n"


def converse_router(*, need_deps, viewed, asked_so_far, guard, store, env=os.environ) -> APIRouter:
    router = APIRouter()
    contexts: dict[str, dict] = {}  # ctx -> {replay_id, moment_idx, expires, turns}

    @router.get("/converse/{sport}/{match_id}/token")
    async def token(
        sport: str, match_id: str, replay_id: str, request: Request, moment_idx: int | None = None
    ):
        key, agent = env.get("ELEVENLABS_API_KEY"), env.get("CONVERSE_AGENT_ID")
        if not (key and agent and env.get("CONVERSE_LLM_SECRET")):
            raise HTTPException(503, "conversation not configured")
        d = need_deps()
        replay = viewed(replay_id)
        moments = d.load_moments(replay.match_id)
        if replay.match_id != match_id or not moments or moments[0]["sport"] != sport:
            raise HTTPException(404, f"no replay of {sport} match {match_id!r}")
        if await asyncio.to_thread(guard.off_air, store):
            raise HTTPException(503, OFF_TODAY)
        past, _ = asked_so_far(replay, moments, moment_idx)
        if not past:
            raise HTTPException(409, "nothing has happened yet")
        if wait := guard.asks.hit(client_ip(request)):
            raise HTTPException(
                429,
                "That's a lot of questions. Try again in a few minutes.",
                {"Retry-After": str(wait)},
            )
        try:
            url = await signed_url(agent, key)
        except (httpx.HTTPError, KeyError) as exc:
            fail("signed url", exc)
            raise HTTPException(502, "conversation could not start") from exc
        now = time.monotonic()
        for ctx in [c for c, v in contexts.items() if v["expires"] < now]:
            del contexts[ctx]
        ctx = secrets.token_urlsafe(24)
        contexts[ctx] = {
            "replay_id": replay_id,
            "moment_idx": past[-1]["idx"],
            "expires": now + CTX_TTL_S,
            "turns": 0,
            "ip": client_ip(request),  # every turn counts against this client's ask limit
        }
        return {"signed_url": url, "ctx": ctx}

    @router.post("/converse/v1/chat/completions")
    async def completions(request: Request):
        secret = env.get("CONVERSE_LLM_SECRET")
        if not secret:
            raise HTTPException(503, "conversation not configured")
        sent = request.headers.get("authorization", "")
        if not hmac.compare_digest(sent.encode(), f"Bearer {secret}".encode()):
            raise HTTPException(401, "bad token")
        body = await request.json()
        messages = body.get("messages") or []
        system = " ".join(words(m.get("content")) for m in messages if m.get("role") == "system")
        found = CTX.search(system)
        held = contexts.get(found[1]) if found else None
        if held is None or held["expires"] < time.monotonic():
            raise HTTPException(404, "unknown conversation")
        if held["turns"] >= MAX_TURNS:
            raise HTTPException(429, "conversation is over")
        held["turns"] += 1
        d = need_deps()
        replay = viewed(held["replay_id"])
        past, lines = asked_so_far(replay, d.load_moments(replay.match_id), held["moment_idx"])
        question = question_of(messages)

        def respond(text: str):
            if body.get("stream", True):
                return StreamingResponse(sse(text), media_type="text/event-stream")
            message = {"role": "assistant", "content": text}
            choice = {"index": 0, "message": message, "finish_reason": "stop"}
            return JSONResponse(
                {
                    "id": f"chatcmpl-{uuid.uuid4().hex}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": "touchline",
                    "choices": [choice],
                }
            )

        if not question or not d.ask:
            return respond(OFF_AIR)
        if await asyncio.to_thread(guard.off_air, store):
            return respond(OFF_TODAY)
        if guard.asks.hit(held["ip"]):
            return respond("That's a lot of questions. Try again in a few minutes.")

        def record(made: dict) -> None:  # as Ask stores its answer: its tokens count in spent_today
            store.append("answers", {**made, "replay_id": held["replay_id"]})
            guard._spent = None

        ask = counted(d.ask, record)
        if body.get("stream", True):
            said = speak(ask, commentator.unrecorded_provider(), question, past, lines)
            return StreamingResponse(sse_of(said), media_type="text/event-stream")
        try:
            said = await asyncio.to_thread(insight.checked_answer, ask, question, past, lines)
        except Exception as exc:  # the status line, never the provider's error
            fail("answer", exc)
            return respond(safe_line(past))
        return respond(said["text"] if said else safe_line(past))

    return router
