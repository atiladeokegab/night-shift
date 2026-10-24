"""Does Ask hold up under a judge's questions? 33 questions across four matches (#319).

    uv run python -m eval.ask_eval                  # offline: the demo provider (FakeProvider)
    uv run python -m eval.ask_eval --provider gold  # a scripted right answer
    uv run python -m eval.ask_eval --provider mubit # keyed: the real model (MUBIT_API_KEY)

Each question is asked at a fixed moment through the route's own path (core/app.py `ask`): "Where
are we?" and "What's the score?" go to agent.status.status, anything else to
insight.checked_answer over agent.commentator.answer. The expected answers were written from the
moments (data/sample) before anything was run: `say` holds the regexes a right answer must all
match, `never` the claims it must not make (a later result, a player who isn't playing). After
the first run, three regexes (time left twice, Mbappé's goals) were narrowed: they took a bare
score's "2" or "3" as the answer. The facts they expect are unchanged. After the first keyed run
(#332), three were widened to take a true answer to the question asked: Mbappé's "second goal" for
what just happened, "we'll find out" for who wins, and "an own goal" alone for who scored last.

An answer is correct when it says everything in `say` and nothing in `never`; refused when it says
neither but declines (or is off air); wrong otherwise. `in message` is whether the request the
model sees already holds every fact in `say`: a fact that isn't there needs a tool or a guess.
"""

from __future__ import annotations

import argparse
import re
import sys

from agent import commentator, status
from core import insight
from core.app import wants_status
from data.matches import load_moments, match_header

WC, CHE, KOBE, ORL = "3869685", "3754092", "0020500591", "7457"


def n(*said: str) -> str:
    """Any of these said as a whole word: "3" or "three"."""
    return r"\b(?:" + "|".join(said) + r")\b"


NO = n(
    "no",
    "not",
    "hasn't",
    "isn't",
    "didn't",
    "can't",
    "cannot",
    "don't",
    "no sign",
    "nobody knows",
    "yet to",
)
# a refusal: the answer declines rather than answers
REFUSED = re.compile(
    r"\b(?:can't|cannot|don't (?:know|have)|no (?:word|record|data|sign)|not sure|"
    r"isn't (?:in|on|playing|part)|not (?:in|on|playing|part)|off air|we'll (?:have to )?see)\b"
    r"|Commentator is off air",
    re.I,
)

QUESTIONS = [
    # the World Cup final, Argentina v France
    {
        "match": WC,
        "idx": 5,
        "q": "What's the score?",
        "say": ["Argentina", n("1", "one"), n("0", "nil", "zero", "nothing")],
        "gold": "First half, 22 minutes played. Argentina lead 1-0.",
    },
    {
        "match": WC,
        "idx": 9,
        "q": "Who scored for Argentina?",
        "say": ["Messi", "Di Mar[ií]a"],
        "gold": "Who's on the scoresheet? Lionel Messi and Ángel Di María, and Argentina lead 2-0.",
    },
    {
        "match": WC,
        "idx": 9,
        "q": "How many shots have Argentina had?",
        "say": [n("6", "six")],
        "gold": "How many shots? Argentina have had six so far, two of them goals, and lead 2-0.",
    },
    {
        "match": WC,
        "idx": 26,
        "q": "What just happened?",
        "say": ["Mbapp", r"2-2|level|equali[sz]|two[- ]all|two each|second"],
        "gold": "What just happened? Kylian Mbappé scores again, and France are level at 2-2!",
    },
    {
        "match": WC,
        "idx": 26,
        "q": "How many shots have France had?",
        "say": [n("4", "four")],
        "gold": "France's shots? Four so far, and two of them went in: it's 2-2.",
    },
    {
        "match": WC,
        "idx": 26,
        "q": "Who wins the World Cup?",
        "trap": True,
        "say": [r"2-2|level|two[- ]all|two each|find out|" + NO],
        "never": [r"\b(?:Argentina|France) (?:wins|won|go on to win)\b"],
        "gold": "Who lifts the trophy? Nobody knows yet: it's level at 2-2 with 80 minutes played.",
    },
    {
        "match": WC,
        "idx": 30,
        "q": "How long is left?",
        "say": [n("87", "eighty-seven") + "|" + n("3 minutes", "three minutes")],
        "gold": "How long? 87 minutes played, about three minutes of normal time left at 2-2.",
    },
    {
        "match": WC,
        "idx": 45,
        "q": "Has Neymar scored?",
        "trap": True,
        "say": [NO],
        "never": [r"Neymar (?:has )?(?:scored|netted|got)\b"],
        "gold": "Neymar? He isn't in this match. It's 2-2 in the first half of extra time.",
    },
    {
        "match": WC,
        "idx": 58,
        "q": "How many goals has Mbappé scored?",
        "say": [n("hat-?trick", "3 goals", "three goals", "three of them", "scored three")],
        "gold": "Mbappé's goals? Three of them, a hat-trick, and it's 3-3 in extra time!",
    },
    {
        "match": WC,
        "idx": 62,
        "q": "Who's ahead in the shootout?",
        "say": ["Argentina", n("2", "two"), n("1", "one")],
        "gold": "Who's ahead? Argentina lead the shootout 2-1 after Paulo Dybala scores.",
    },
    # Chelsea v Tottenham, the Battle of the Bridge
    {
        "match": CHE,
        "idx": 11,
        "q": "Who scored?",
        "say": ["Kane"],
        "gold": "Who scored? Harry Kane, and Tottenham Hotspur lead 1-0!",
    },
    {
        "match": CHE,
        "idx": 19,
        "q": "What's the score?",
        "say": ["Tottenham", n("2", "two"), n("0", "nil", "zero", "nothing")],
        "gold": "First half, 45 minutes played. Tottenham Hotspur lead 2-0.",
    },
    {
        "match": CHE,
        "idx": 25,
        "q": "How many shots have Chelsea had?",
        "say": [n("7", "seven")],
        "gold": "Chelsea's shots? Seven so far, none in, and Tottenham Hotspur lead 2-0.",
    },
    {
        "match": CHE,
        "idx": 30,
        "q": "Who's winning?",
        "say": ["Tottenham", n("2", "two"), n("1", "one")],
        "gold": "Who's in front? Tottenham Hotspur, 2-1 up on Chelsea.",
    },
    {
        "match": CHE,
        "idx": 37,
        "q": "What just happened?",
        "say": ["Hazard", r"2-2|level|equali[sz]|two[- ]all|two each"],
        "gold": "What just happened? Eden Hazard scores for Chelsea, and it's level at 2-2!",
    },
    {
        "match": CHE,
        "idx": 40,
        "q": "How much time is left?",
        "say": [n("88", "eighty-eight") + "|" + n("2 minutes", "two minutes")],
        "gold": "Time left? 88 minutes played, about two minutes of normal time to go at 2-2.",
    },
    {
        "match": CHE,
        "idx": 45,
        "q": "How many yellow cards have Tottenham had?",
        "say": [n("9", "nine")],
        "gold": "Tottenham's yellow cards? Nine of them now, and it's still 2-2.",
    },
    {
        "match": CHE,
        "idx": 20,
        "q": "Did Frank Lampard score?",
        "trap": True,
        "say": [NO],
        "never": [r"Lampard (?:has )?(?:scored|netted|got)\b"],
        "gold": "Frank Lampard? He isn't in this match. Tottenham Hotspur lead 2-0 at half-time.",
    },
    {
        "match": CHE,
        "idx": 26,
        "q": "Does Hazard score later?",
        "trap": True,
        "say": [r"2-1|" + NO],
        "never": [r"\b(?:yes|he does|he will)\b", n("82", "2-2")],
        "gold": "Will Hazard score? Nobody knows yet: Tottenham Hotspur lead 2-1 after 57 minutes.",
    },
    # Kobe's 81, Lakers v Raptors
    {
        "match": KOBE,
        "idx": 1,
        "q": "Who hit that three?",
        "say": ["Mike James|James"],
        "gold": "Who hit the three? Mike James, and the Toronto Raptors lead 5-3.",
    },
    {
        "match": KOBE,
        "idx": 9,
        "q": "Who's winning?",
        "say": ["Lakers", n("87"), n("85")],
        "gold": "Who's in front? The Los Angeles Lakers, 87-85.",
    },
    {
        "match": KOBE,
        "idx": 13,
        "q": "How much time is left?",
        "say": [r"6:32|six minutes|6 minutes|six thirty-two"],
        "gold": "Time left? 6:32 to go in the fourth quarter, Lakers up 102-93.",
    },
    {
        "match": KOBE,
        "idx": 14,
        "q": "How many points does Kobe have?",
        "say": [n("67", "sixty-seven")],
        "gold": "Kobe's points? 67 tonight, and the Lakers lead 108-96.",
    },
    {
        "match": KOBE,
        "idx": 21,
        "q": "What just happened?",
        "say": ["Vujacic", "steal|stole|picks? off|swipe"],
        "gold": "Sasha Vujacic steals it from Charlie Villanueva! Lakers lead 120-102.",
    },
    {
        "match": KOBE,
        "idx": 21,
        "q": "How many points does Kobe have now?",
        "say": [n("79", "seventy-nine")],
        "gold": "Kobe's points? 79 tonight, and the Lakers lead 120-102.",
    },
    {
        "match": KOBE,
        "idx": 10,
        "q": "How many points has LeBron James scored?",
        "trap": True,
        "say": [NO],
        "never": [r"LeBron[^.]*\b\d+ points"],
        "gold": "LeBron James? He isn't in this game. The Lakers lead 91-85.",
    },
    {
        "match": KOBE,
        "idx": 5,
        "q": "What's the final score?",
        "trap": True,
        "say": [r"77|67|" + NO],
        "never": [n("122", "104", "81")],
        "gold": "The final score? Not there yet: the Toronto Raptors lead 77-67 in the third.",
    },
    # Orlando Pride v North Carolina Courage
    {
        "match": ORL,
        "idx": 14,
        "q": "Who scored?",
        "say": ["McDonald"],
        "gold": "Who scored? Jessica McDonald, and the North Carolina Courage lead 1-0!",
    },
    {
        "match": ORL,
        "idx": 20,
        "q": "How many shots have the Courage had?",
        "say": [n("18", "eighteen")],
        "gold": "The Courage's shots? Eighteen so far, and they lead 1-0.",
    },
    {
        "match": ORL,
        "idx": 26,
        "q": "What's the score?",
        "say": ["Carolina", n("3", "three"), n("2", "two")],
        "gold": "Second half, 63 minutes played. North Carolina Courage lead 3-2.",
    },
    {
        "match": ORL,
        "idx": 38,
        "q": "What just happened?",
        "say": ["Hill", r"3-3|level|equali[sz]|three[- ]all|three each"],
        "gold": "What just happened? Rachel Hill scores for Orlando, and it's level at 3-3!",
    },
    {
        "match": ORL,
        "idx": 42,
        "q": "Who scored the last goal?",
        "say": ["own goal|Poliana"],
        "gold": "The last goal? An own goal by Orlando's Poliana, and the Courage lead 4-3.",
    },
    {
        "match": ORL,
        "idx": 30,
        "q": "Has Megan Rapinoe scored?",
        "trap": True,
        "say": [NO],
        "never": [r"Rapinoe (?:has )?(?:scored|netted|got)\b"],
        "gold": "Megan Rapinoe? She isn't in this match. The North Carolina Courage lead 3-2.",
    },
]


def verdict(text: str, q: dict) -> str:
    if any(re.search(rx, text, re.I) for rx in q.get("never", ())):
        return "wrong"
    if all(re.search(rx, text, re.I) for rx in q["say"]):
        return "correct"
    return "refused" if REFUSED.search(text) else "wrong"


class Recording:
    """The provider the run uses, with every request kept: the first one is what the model saw."""

    def __init__(self, provider):
        self.provider, self.requests = provider, []

    def call(self, request: dict) -> dict:
        self.requests.append(request)
        return self.provider.call(request)


class Gold:
    """A model that always gives the question's right answer."""

    def __init__(self, text: str):
        self.text = text

    def call(self, request: dict) -> dict:
        usage = {"input_tokens": 0, "output_tokens": 0}
        return {
            "content": [{"type": "text", "text": self.text}],
            "usage": usage,
            "request_id": "gold",
        }


def provider_for(kind: str, q: dict, route: str):
    if kind == "fake":
        return commentator.FakeProvider()
    if kind == "gold":
        return Gold(q["gold"])
    # mubit: each path's own provider, as the route gets it
    return (
        commentator.default_provider() if route == "status" else commentator.unrecorded_provider()
    )


def ask(q: dict, kind: str) -> dict:
    """One question through the route's path, as core/app.py's ask runs it."""
    header = match_header(q["match"])
    past = load_moments(q["match"])[: q["idx"] + 1]
    route = "status" if wants_status(q["q"]) else "ask"
    rec = Recording(provider_for(kind, q, route))

    def answer(question, past, lines, wrong=()):
        return commentator.answer(question, past, lines, header, rec, wrong)

    try:
        if route == "status":
            said = status.status(past, header, provider=rec)
        else:
            said = insight.checked_answer(answer, q["q"], past, [])
    except Exception as exc:  # the route's off-air line
        said = {"text": f"Commentator is off air for a moment ({type(exc).__name__})"}
    said = said or {"text": "Commentator is off air for a moment"}
    text = said["text"]
    message = rec.requests[0]["messages"][0]["content"] if rec.requests else ""
    facts = "n/a" if q.get("trap") else all(re.search(rx, message, re.I) for rx in q["say"])
    return {
        "route": route,
        "text": text,
        "verdict": verdict(text, q),
        "fallback": bool(said.get("fallback")),
        "in_message": facts,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--provider", choices=("fake", "gold", "mubit"), default="fake")
    args = ap.parse_args(argv)
    rows = [(q, ask(q, args.provider)) for q in QUESTIONS]
    print(f"## Ask eval, provider {args.provider}\n")
    print("| # | Match | At | Question | Route | In message | Answer | Verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for i, (q, r) in enumerate(rows, 1):
        said = r["text"].replace("|", "/") + (" (fallback)" if r["fallback"] else "")
        facts = {True: "yes", False: "no"}.get(r["in_message"], r["in_message"])
        print(
            f"| {i} | {q['match']} | {q['idx']} | {q['q']} | {r['route']} | {facts} "
            f"| {said} | {r['verdict']} |"
        )
    counts = {v: sum(r["verdict"] == v for _, r in rows) for v in ("correct", "wrong", "refused")}
    facts = [r["in_message"] for _, r in rows if r["in_message"] != "n/a"]
    print(
        f"\n{counts['correct']} correct, {counts['wrong']} wrong, {counts['refused']} refused "
        f"of {len(rows)}; the facts are in the message for {sum(facts)} of {len(facts)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
