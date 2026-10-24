"""Let them watch (#291): one short note of what a viewer's shared screen shows, from one frame.

The note goes in the next line's user message (`build_request`'s `seen`). It is never a fact: its
digits are stripped and a note that names anyone is dropped. Its own system prompt makes it its own
Mubit task, sent with recording off. The frame is never stored or logged: it lives for one call.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

SYSTEM = (Path(__file__).resolve().parent / "look.md").read_text(encoding="utf-8")
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 40
MAX_WORDS = 12
ASK = "What does the picture show?"
# a number said in words is a number too: the lines' numbers come only from the match data
NUMBER_WORDS = re.compile(
    r"\b(zero|nil|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"\w+teen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|"
    r"\w+teenth|\w+tieth|dozens?|hundreds?|hundredth|thousands?|thousandth|millions?|"
    r"half|halves|minute|minutes)\b",
    re.I,
)


def request(image: str) -> dict:
    """The vision request for one base64 JPEG frame."""
    return {
        "model": os.environ.get("LOOK_MODEL") or MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image},
                    },
                    {"type": "text", "text": ASK},
                ],
            }
        ],
    }


def clean(text: str, names=()) -> str | None:
    """The model's phrase as a note: digits stripped, at most MAX_WORDS words; None for no note, a
    number in words or in another script (², ½), or any name (an all-caps word, a capital after the
    first word, or a word of a match's name)."""
    said = text.strip().splitlines()[0] if text.strip() else ""
    said = re.sub(r"\d+(?:[:.,'’\-–]\d*)*", " ", said)  # 2-1, 45:00, 90', No. 9
    said = re.sub(r"(?<!\w)[^\w\s]+(?!\w)", " ", said)  # what the digits left: a lone - or :
    words = said.strip(" \"'“”.").split()[:MAX_WORDS]
    if not words or (len(words) == 1 and words[0].lower() == "nothing"):
        return None
    note = " ".join(words)
    if NUMBER_WORDS.search(note) or any(c.isnumeric() for c in note):
        return None
    if any(w[0].isupper() for w in words[1:]) or any(w.isupper() and len(w) > 1 for w in words):
        return None
    # shortcut: a name as the first word passes unless it is one of the match's names (the players
    # and teams); a word list or a tagger if the model starts doing that
    parts = {p.lower() for name in names for p in re.findall(r"\w{3,}", name or "")}
    if parts & {w.lower() for w in re.findall(r"\w+", note)}:
        return None
    return note[0].lower() + note[1:]


def see(image: str, names=(), provider=None) -> dict:
    """One note for the frame `image` (base64 JPEG), or None, with the call's model and tokens for
    the daily spend. Offline (no MUBIT_API_KEY): no call, so no note: the offline commentator has
    nothing to look with."""
    if provider is None:
        if not os.environ.get("MUBIT_API_KEY"):
            return {"note": None}
        from agent.commentator import unrecorded_provider

        provider = unrecorded_provider()
    sent = request(image)
    reply = provider.call(sent)
    said = " ".join(b["text"] for b in reply["content"] if b["type"] == "text")
    usage = reply.get("usage") or {}
    return {
        "note": clean(said, names),
        "model": sent["model"],
        "tokens_in": usage.get("input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
    }
