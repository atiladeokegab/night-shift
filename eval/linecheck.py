"""Line check (#209): does a commentary line's claim match the moment's facts? A third Mubit task
whose answer is short and exact: one JSON object, four fields, each ok, wrong or not_said.

The gold label comes from code, never a model: core/insight.py's checks (`_false_lead`'s claims,
`_wrong_margin`, `wrong_event`, `said`) plus narrow detectors for the score, the named player's
running total and the event. A line whose numbers code can't put to a field, or that it can't
otherwise decide, gets no label (`gold` returns None) and is dropped, never guessed."""

from __future__ import annotations

import hashlib
import json
import re
from string import Template

from agent.commentator import _match, _outcome, _score
from agent.status import _lead, _people
from core import insight
from data.matches import leader

FIELDS = ("score", "leader", "player_total", "event")
LABELS = ("ok", "wrong", "not_said")
HELD_OUT = ("3913122", "9636")  # the WSL match and the F1 race: never sent to Mubit

SYSTEM = """You check one line of live sports commentary against the facts of its moment.

The user message gives the line, then the moment's facts: the score, who leads, the named player's running total, and what happened. For each of four fields, say whether the line's claim about it matches the facts:
- "ok": the line states it, and it matches the facts.
- "wrong": the line states it, and it contradicts the facts.
- "not_said": the line does not state it.

Fields: score (the score or standing, in any form, including a margin or a cricket chase's need), leader (who is in front, or that it is level), player_total (the named player's own running total tonight: points, goals), event (what just happened: the kind of event and how it ended).

Reply with exactly one JSON object and nothing else, in this form:
{"score": "ok", "leader": "not_said", "player_total": "not_said", "event": "ok"}"""  # noqa: E501

MESSAGE = Template(
    "Line: $line\nSport: $sport\nMatch: $match\nScore: $score\nLeader: $lead\n"
    "Player total: $total\nEvent: $event"
)


def example_id(match_id: str, idx: int, text: str) -> str:
    return hashlib.sha1(f"{match_id}|{idx}|{text}".encode()).hexdigest()[:12]


# --- the facts -------------------------------------------------------------------------------


def _goals(m: dict, past: list[dict]) -> int | None:
    """The shooter's goals in the match up to and including m (a shootout's kicks don't count)."""
    who = (m.get("players") or {}).get("shooter")
    if not who:
        return None
    return sum(
        p["type"] == "Shot"
        and p["outcome"] == "Goal"
        and p["period"] != 5
        and p["players"].get("shooter") == who
        for p in [*past, m]
    )


def player_total(m: dict, past: list[dict]) -> tuple[str, float] | None:
    """The named player and their running total: points (basketball), goals (football)."""
    if m["sport"] == "basketball" and m["detail"].get("player_points"):
        return insight._who(m), float(m["detail"]["player_points"])
    if m["sport"] == "football" and m["type"] == "Shot":
        return m["players"]["shooter"], float(_goals(m, past))
    return None


def facts(header: dict, m: dict, past: list[dict]) -> str:
    total = player_total(m, past)
    unit = "points" if m["sport"] == "basketball" else "goals"
    return MESSAGE.substitute(
        line="$line",
        sport=m["sport"],
        match=_match(header),
        score=_score(header, m),
        lead=_lead(m),
        total=f"{total[0]}, {total[1]:g} {unit} tonight" if total else "none",
        event=f"{m['type']}, {_outcome(m)} ({m['team'] or 'no team'}; {_people(m)})",
    )


def build_request(header: dict, m: dict, past: list[dict], text: str, model: str) -> dict:
    return {
        "model": model,
        "max_tokens": 60,
        "temperature": 0,
        "system": SYSTEM,
        "metadata": {"user_id": "line-check"},
        "messages": [{"role": "user", "content": facts(header, m, past).replace("$line", text, 1)}],
    }


def parse(text: str) -> dict | None:
    """The reply as {field: label}, or None unless it is exactly one such JSON object."""
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(out, dict) or set(out) != set(FIELDS):
        return None
    return out if all(out[f] in LABELS for f in FIELDS) else None


def dumps(label: dict) -> str:
    return json.dumps({f: label[f] for f in FIELDS})


# --- the claims ------------------------------------------------------------------------------

ZERO = {"nil", "nothing", "zero", "love"}
ORDINAL = {**insight.ORDINALS, "st": None, "nd": None, "rd": None, "th": None}


def tokens(text: str) -> list:
    """`insight.said`, with "," where the line has punctuation: "two, ninety seconds" and "1:47"
    are no score."""
    out = []
    for chunk in re.split(r"(?:[^\w\s'’.-]|(?<!\d)\.|\.(?!\d))+", text):
        out += [*insight.said(chunk), ","] if chunk.strip() else []
    return out[:-1]


def _num(t) -> float | None:
    if isinstance(t, float):
        return t
    return 1.0 if t == "one" else 0.0 if t in ZERO else None


def _names(header: dict) -> dict[tuple[str, ...], str]:
    """Each way a line names a team, as said() tokens, to its side."""
    side, _ = insight._sides(header)
    return {tuple(w for w in insight.said(n) if isinstance(w, str)): s for n, s in side.items()}


def _team_before(t: list, i: int, names: dict) -> str | None:
    for n in sorted(names, key=len, reverse=True):
        if n and tuple(t[max(0, i - len(n)) : i]) == n:
            return names[n]
    return None


def score_pairs(t: list, header: dict) -> list[tuple[dict | tuple, list[int]]]:
    """Scores a home/away line says, from said() tokens: "Lakers 122, Raptors 104" (by side),
    "113 to 96", "86-85", "one nil", "two all". Each with the token indices it used."""
    names, out, used = _names(header), [], set()
    for i in range(len(t)):
        if i in used or _num(t[i]) is None:
            continue
        a, rest = _num(t[i]), t[i + 1 : i + 4]
        side = _team_before(t, i, names)
        if side:  # TEAM n TEAM n
            for j in range(i + 2, min(i + 6, len(t))):
                other = _team_before(t, j, names)
                if other and other != side and _num(t[j]) is not None:
                    out.append(({side: a, other: _num(t[j])}, [i, j]))
                    used |= {i, j}
                    break
            if i in used:
                continue
        if rest and _num(rest[0]) is not None and t[i] != "one":  # "86-85", "three two"
            out.append(((a, _num(rest[0])), [i, i + 1]))
        elif rest and _num(rest[0]) is not None and _num(rest[0]) == 0:  # "one nil"
            out.append(((a, 0.0), [i, i + 1]))
        elif len(rest) > 1 and rest[0] == "to" and _num(rest[1]) is not None:  # "113 to 96"
            out.append(((a, _num(rest[1])), [i, i + 2]))
        elif rest and rest[0] in ("all", "apiece", "each"):  # "one apiece"
            out.append(((a, a), [i]))
        else:
            continue
        used |= set(out[-1][1])
    return out


def _margins(text: str, header: dict) -> list[float]:
    """The margins a line gives a team ("Lakers down ten"), read as `insight._wrong_margin` does."""
    _, names = insight._sides(header)
    out = []
    for hit in re.finditer(rf"\b(?:{names}){insight.MARGIN}", text, re.I):
        if len(insight.said(hit[1])) > 1:
            continue
        # tokens, not said: "down one, eighteen seconds left" is a margin, not a score
        n, *after = tokens(text[hit.start(1) : hit.start(1) + 48]) or [None]
        n = 1.0 if n == "one" else n
        if isinstance(n, float) and not (
            after and (isinstance(after[0], float) or after[0] in ("to", "one"))
        ):
            out.append(n)
    return out


TRAILS = r"\s+(?:(?:are|is|now|still)\s+){0,2}(?:trail|trails|trailing|behind|down)\b(?!\s+(?:the|to|in|on|at)\b)"  # noqa: E501
WINS = r"\s+(?:(?:have|has|will)\s+)?(?:win|wins|won|take it|takes it|beat|beats)\b(?!\s+away)(?!\s+(?:the|a|in|on)\s+(?:ball|toss|header|free|corner|penalty))"  # noqa: E501
_NUMBER = "|".join([*insight.UNITS[1:], *insight.TENS, r"\d+", "nil"])
LEVEL = re.compile(
    rf"\b(?:level|all square|tied|apiece|equali[sz]e[sd]?|ties it|tie it|(?:{_NUMBER})[ -]all)\b"
    r"(?! the)",
    re.I,
)


def lead_claims(text: str, header: dict) -> list[str | None]:
    """Who the line says leads: "home", "away", or None for level. Questions are no claim."""
    side, names = insight._sides(header)
    other = {"home": "away", "away": "home"}
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if sentence.rstrip().endswith("?"):
            continue
        out += [side[c.lower()] for c in re.findall(rf"\b({names}){insight.LEADS}", sentence, re.I)]
        out += [side[c.lower()] for c in re.findall(rf"\b({names}){WINS}", sentence, re.I)]
        out += [other[side[c.lower()]] for c in re.findall(rf"\b({names}){TRAILS}", sentence, re.I)]
        out += [None] * len(LEVEL.findall(sentence))
    return out


POINTS = ("point", "points", "pts")
NOT_TOTAL = {"by", "lead", "leads", "up", "down", "win", "wins", "trail", "trails", "ahead"}


def point_claims(t: list) -> list[tuple[float, int]]:
    """ "49 points", "his 72nd point", "fifty-nine points": each number and its index."""
    out = []
    for i, w in enumerate(t):
        if not isinstance(w, float):
            continue
        j = i + 1 + (i + 1 < len(t) and t[i + 1] in ("st", "nd", "rd", "th"))
        if j < len(t) and t[j] in POINTS and not NOT_TOTAL & set(t[max(0, i - 3) : i]):
            out.append((w, i))
    return out


def goal_claims(t: list) -> tuple[list[tuple[float, list[int]]], bool]:
    """A football player's own tally: "brace", "hat-trick", "his second goal". And whether the
    line counts a goal it can't pin on the player ("the third goal" may be the team's)."""
    out, unsure = [], False
    for i, w in enumerate(t):
        if w == "brace":
            out.append((2.0, []))
        elif w == "hat" and t[i + 1 : i + 2] == ["trick"]:
            out.append((3.0, []))
        n = insight.ORDINALS.get(w) if isinstance(w, str) else None
        if isinstance(w, float) and t[i + 1 : i + 2] and t[i + 1] in ("st", "nd", "rd", "th"):
            n = w
        if n and t[i + 1 : i + 3] and ({"goal", "of"} & set(t[i + 1 : i + 3])):
            if t[i - 1 : i] and t[i - 1] in ("his", "her", "s"):
                out.append((float(n), [i]))
            else:
                unsure = True
    return out, unsure


# event words, per sport and kind
def _re(words: str) -> re.Pattern:
    return re.compile(rf"\b(?:{words})\b", re.I)


THREE = _re(
    r"three[- ]?pointers?|3[- ]?pointers?|triple"
    r"|from (?:deep|downtown|three(?![- ]?f(?:oo|ee)t)|long range|way out)"
    r"|beyond the arc|for three|from the corner three"
    r"|(?:the|a|another) three(?! (?:free|points?|seconds?|minutes?|quarters?|of|to))"
)
TWO_ONLY = _re(r"lay[- ]?ups?|dunks?|slams?|two[- ]pointers?|for two|floaters?|hook shot|tip[- ]in")
FIELD_GOAL = _re(
    r"jump(?:er| ?shot)|shot|bucket|basket|scores?|drains?|hits?|knocks? (?:it )?down|buries"
    r"|nails?|sinks?|fade ?away|pull[- ]up|finish(?:es)?|banks?|swish|another|\w+[- ]footer|good"
    r"|from (?:\d+|\w+teen|twenty\S*|thirty\S*)|two more"
)
FREE_THROW = _re(r"free throws?|at the line|from the line|foul line|charity stripe|freebies?")
STEAL = _re(r"steals?|stolen|picks? (?:it|his pocket)|strips?|takes it away|turnover|pickpocket")
GAME_OVER = _re(
    r"final buzzer|buzzer|that's the game|game over|it's over|final|wins?|won|victory|champions?"
)
SCORED = _re(r"takes? the lead|ties? it|go(?:es)? (?:up|ahead)|puts? \w+ ahead|level")

CARD = _re(r"cards?|book(?:ed|ing)?|caution(?:ed)?|yellow|red|sent off|sees red")
FOUL = _re(r"fouls?|fouled|brings? down|clips?|trips?|free kick|challenge|tackle|late")
SUB = _re(
    r"on for|off for|replaces?|replaced|substitut\w*|comes? on|change|makes? way|on comes"
    r"|introduc\w*"
    r"|fresh legs|enters|into the action"
)
INJURY = _re(r"injur\w*|down|treatment|stoppage|hurt|knock|pain|physio|medical|stretcher|holding")
FULL_TIME = _re(
    r"full[- ]time|final whistle|whistle|over|ends?|ended|draw|drawn|penalties|shootout|extra time"
)
GOAL = _re(
    r"goal|scores?|scored|nets?|converts?|finish(?:es)?|into the (?:net|corner)|back of the net"
    r"|buries|slots?|fires? home|heads? home|tucks?|from the spot|penalty|equali[sz]e[sd]?"
    r"|level(?:s|led)? it"
    r"|level(?:l)?er|takes? the lead|puts? \w+ ahead|deadlock|doubled?|pulls? one back|sends? it in"
)
MISSED = _re(r"wide|misses|missed|saved|blocked|off target|over the bar|hits the (?:post|bar)")

F1_KIND = {
    "Lead change": _re(
        r"takes? the lead|into the lead|lead change|new leader|P1|first place|leads?"
    ),
    "Overtake": _re(r"overtakes?|passes|past|moves? (?:up|into)|P\d|takes? \w+ place|up to"),
    "Pit stop": _re(r"pits?|pit stop|pit lane|tyres?|intermediates?|inters|box(?:es)?"),
    "Safety car": _re(r"safety car|VSC|virtual"),
    "Red flag": _re(r"red flag|halted|suspended|stopped"),
    "Lights out": _re(r"lights out|away we go|race start|start|first corner|turn one"),
    "Finish": _re(r"chequered flag|checkered flag|wins?|won|victory|takes the win"),
    "Last lap": _re(r"last lap|final lap|bell"),
    "Conditions": _re(r"grip|conditions|wet|rain|slippery|treacherous|spray|damp"),
}
F1_STRONG = {  # a claim that is surely of its own kind, wrong on any other
    "Pit stop": _re(r"pits|into the pits|pit stop"),
    "Safety car": _re(r"safety car"),
    "Red flag": _re(r"red flag"),
    "Lights out": _re(r"lights out"),
    "Finish": _re(r"chequered flag|checkered flag"),
}


def _event_claim_numbers(t: list, used: set[int]) -> tuple[set[float], set[int]]:
    """A cricket line's boundary calls ("FOUR!", "for six") as 4.0/6.0, not the 4 of "96 for 4"
    nor the 6 of "need 6 from 3 balls"; with the indices they used."""
    after = {"for", "balls", "ball", "overs", "over", "wickets", "wicket", "down", "needed", "to"}
    after |= {"sixes", "fours", "boundaries", "maximums", "dots", "wides", "deliveries"}
    before = {"need", "needs", "needing", "needed", "from", "off", "last", "in", "within", "for"}
    claims, idx = set(), set()
    for i, w in enumerate(t):
        if i in used or w not in (4.0, 6.0):
            continue
        prev = t[i - 1] if i else None
        nxt = t[i + 1] if i + 1 < len(t) else None
        then = t[i + 2] if i + 2 < len(t) else None
        if nxt in ("runs", "run", "from", "off") and (
            isinstance(then, float) or then in ("from", "off", "needed", "to", "required")
        ):  # "6 from 3 balls", "six runs needed"
            continue
        boundary = prev == "for" and not (i > 1 and isinstance(t[i - 2], float))
        if boundary or (nxt not in after and prev not in before and not isinstance(prev, float)):
            claims.add(w)
            idx.add(i)
    return claims, idx


WICKET = _re(
    r"wicket|lbw|stumped|run out|caught|departs|dismissed|(?-i:OUT)|is out|he's out|gone|falls"
    r"|bowled him"
    r"|castled|cleaned up|timber|walks|bowled(?=\s*[!,.])"
)
CRICKET_BOUNDARY = _re(r"boundary|boundaries|maximum|into the stands|over the ropes?|rope")
CRICKET_RUNS = {
    "1 run": _re(r"single|one run|a run|runs?|quick one|takes one|gets one|nudged|pushed"),
    "2 runs": _re(r"two|couple|2 runs|runs"),
    "3 runs": _re(r"three|3 runs|runs"),
    "wide": _re(r"wide|wides"),
    "dot ball": _re(r"dot|no run|beaten|misses|nothing|swing and a miss"),
}


def event_label(text: str, t: list, m: dict, used: set[int]) -> tuple[str | None, set[int]]:
    """ok, wrong or not_said for what happened; None when code can't decide. With the indices of
    the numbers the event claims used."""
    kind, outcome, sport = m["type"], m.get("outcome") or "", m["sport"]
    if sport == "football":
        wrong = [w for w in insight.wrong_event(text, m) if "never says how" not in w]
        if kind != "Shot" and any(
            w.startswith("a goal is called") for w in wrong
        ):  # "France level it through Mbappé's double" over a booking
            return None, set()  # recalls a goal; code can't tell a recap from a wrong call
        card = m["detail"].get("card", "")
        if card == "Yellow Card" and _re(r"red card|sees red|straight red|sent off").search(text):
            wrong.append("red called on a yellow")
        if card == "Red Card" and _re(r"yellow").search(text):
            wrong.append("yellow called on a red")
        if kind == "Shot" and outcome == "Goal" and MISSED.search(text):
            wrong.append("a miss called on a goal")
        if wrong:
            return "wrong", set()
        said_it = {
            "Shot": GOAL if outcome == "Goal" else insight.ENDED,
            "Foul Committed": _re(f"{FOUL.pattern}|{CARD.pattern}"),
            "Bad Behaviour": CARD,
            "Substitution": SUB,
            "Injury Stoppage": INJURY,
            "Full time": FULL_TIME,
        }.get(kind)
        if said_it is None:
            return None, set()
        if said_it.search(text) or insight.GOAL_WORDS.search(text) and outcome == "Goal":
            return "ok", set()
        # a goal's line that only names the scorer and the new score implies the goal: undecided
        return (None if outcome == "Goal" else "not_said"), set()
    if sport == "basketball":
        value = {i: w for w, i in point_claims(t) if w <= 3}  # "three points" is the basket
        has_value = float(outcome.split()[0]) if outcome[:1].isdigit() else None
        if any(v != has_value for v in value.values()):
            return "wrong", set(value)
        if kind == "Field goal":
            three, two = THREE.search(text), TWO_ONLY.search(text)
            if (has_value == 2 and three) or (has_value == 3 and two):
                return "wrong", set(value)
            said_it = three or two or FIELD_GOAL.search(text) or value
        elif kind == "Free throw":
            if THREE.search(text) or TWO_ONLY.search(text):
                return "wrong", set(value)
            said_it = FREE_THROW.search(text) or value
        elif kind == "Steal":
            said_it = STEAL.search(text)
        elif kind == "End of game":
            said_it = GAME_OVER.search(text)
        else:
            return None, set()
        if not said_it and SCORED.search(text):  # a basket implied, its kind unsaid: undecided
            return None, set()
        return ("ok" if said_it else "not_said"), set(value)
    if sport == "cricket":
        nums, idx = _event_claim_numbers(t, used)
        wicket, boundary = WICKET.search(text), CRICKET_BOUNDARY.search(text)
        if kind in ("Four", "Six"):
            own = 4.0 if kind == "Four" else 6.0
            if wicket or nums - {own}:
                return "wrong", idx
            return ("ok" if own in nums or boundary else "not_said"), idx
        if kind == "Wicket":  # "caught at the boundary" is a wicket still
            if nums:
                return "wrong", idx
            return ("ok" if wicket else "not_said"), idx
        runs = CRICKET_RUNS.get(outcome)
        if runs is None:
            return None, idx
        if nums:  # "one wicket and one run to win" names no wicket here
            return "wrong", idx
        return ("ok" if runs.search(text) else "not_said"), idx
    own = F1_KIND.get(kind)
    if own is None:
        return None, set()
    if any(k != kind and r.search(text) for k, r in F1_STRONG.items()):
        return "wrong", set()
    return ("ok" if own.search(text) else "not_said"), set()


def _lap_label(t: list, m: dict) -> tuple[str, set[int]]:
    """F1's standing in a line: "lap 32 of 69"."""
    s, label, used = m["score"], "not_said", set()
    for i, w in enumerate(t[:-1]):
        if w == "lap" and _num(t[i + 1]) is not None:
            n, used = _num(t[i + 1]), used | {i + 1}
            of = t[i + 3] if t[i + 2 : i + 3] == ["of"] and i + 3 < len(t) else None
            if of is not None:
                used.add(i + 3)
            ok = n in (s["lap"], m["period"]) and (of is None or of == s["laps"])
            label = "wrong" if not ok or label == "wrong" else "ok"
    return label, used


def _f1_leader(text: str, m: dict) -> str | None:
    drivers = {c["driver"] for c in m["score"]["top"]} | set(m["players"].values())
    p1 = min(m["score"]["top"], key=lambda c: c["pos"])["driver"]
    names = {n.lower(): d for d in drivers for n in (d, d.split()[-1])}
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    # a driver, then a claim of P1 right after: "Ocon still leads", "MAX VERSTAPPEN! WINS"
    claim = (
        rf"\b({alt})[\s!—–-]*(?:(?:still|now|is|has|just)\s+)?(?:leads|leading|takes? the lead"
        r"|in the lead|into the lead|wins|won|takes? (?:it|the win|victory)|is the leader"
        r"|(?:in|into|takes) (?:P1|first place))\b"
    )
    said = [names[c.lower()] for c in re.findall(claim, text, re.I)]
    said += [
        names[c.lower()] for c in re.findall(rf"\b(?:leader|lead to),?\s+({alt})\b", text, re.I)
    ]
    if not said:  # "Red Bull Racing wins": a team's claim, which code doesn't read
        return None if _re(r"wins?|won|victory").search(text) else "not_said"
    return "ok" if all(d == p1 for d in said) else "wrong"


def gold(header: dict, m: dict, past: list[dict], text: str) -> dict | None:
    """The four labels for `text` said over moment m, or None when code can't decide one."""
    if insight.talks_to_itself(text):
        return None
    t = tokens(text)
    heard = {
        i for i, w in enumerate(t) if isinstance(w, float) and (i == 0 or t[i - 1] != "number")
    }
    used: set[int] = set()
    s, sport = m["score"], m["sport"]
    total = player_total(m, past)

    # score
    if "home" in s:
        want = {"home": float(s["home"]), "away": float(s["away"])}
        tallies = [want] + (
            [{k: float(v) for k, v in m["detail"]["shootout"].items()}]
            if "shootout" in m["detail"]
            else []
        )
        pairs = score_pairs(t, header)
        right = [
            any(
                p == tl if isinstance(p, dict) else sorted(p) == sorted(tl.values())
                for tl in tallies
            )
            for p, _ in pairs
        ]
        margins = _margins(text, header)
        diff = {abs(tl["home"] - tl["away"]) for tl in tallies}
        right += [n in diff for n in margins]
        for _, idx in pairs:
            used |= set(idx)
        used |= {i for i in heard if t[i] in margins}
        score = "not_said" if not right else "ok" if all(right) else "wrong"
    elif sport == "cricket":
        claims = []
        for i in range(1, len(t) - 1):
            a, b = _num(t[i - 1]), _num(t[i + 1])  # "one for one" too
            if t[i] == "for" and a is not None and b is not None:
                runs_w = {(s["runs"], s["wickets"]), (s["wickets"], s["runs"])}
                claims.append((a, b) in runs_w)
                used |= {i - 1, i + 1}
        if "target" in s:
            need = float(max(0, s["target"] - s["runs"]))
            for i, w in enumerate(t[:-1]):
                if w in ("need", "needs", "needing", "needed", "require", "requires"):
                    j = i + 1 + (t[i + 1] in ("just", "only", "another") and i + 2 < len(t))
                    if _num(t[j]) is not None:
                        claims.append(_num(t[j]) == need)
                        used.add(j)
        score = "not_said" if not claims else "ok" if all(claims) else "wrong"
    else:
        score, lap_used = _lap_label(t, m)
        used |= lap_used

    # leader
    if "home" in s:
        claims = lead_claims(text, header)
        if not claims and _re(r"wins?|won|victory|winners?|champions?").search(text):
            return None  # "the Albion hold on for the win": a claim code doesn't read
        # "level at three all" is true of a shootout's match too, whoever leads the kicks
        right = [c == leader(m) or (c is None and s["home"] == s["away"]) for c in claims]
        lead = "not_said" if not claims else "ok" if all(right) else "wrong"
    elif sport == "cricket":
        if _re(r"lead|leads|ahead|wins?|won|victory|beat|beats|in control").search(
            re.sub(r"\bto win\b", "", text, flags=re.I)
        ):
            return None
        lead = "not_said"
    else:
        lead = _f1_leader(text, m)
        if lead is None:
            return None

    # player total
    if sport == "basketball":
        claims = [(n, i) for n, i in point_claims(t) if n > 3]
        used |= {i for _, i in claims}
        if claims and not total:
            return None
        ptotal = (
            "not_said" if not claims else "ok" if all(n == total[1] for n, _ in claims) else "wrong"
        )
    elif sport == "football":
        claims, unsure = goal_claims(t)
        if unsure or (claims and not total):
            return None
        for _, idx in claims:
            used |= set(idx)
        ptotal = (
            "not_said" if not claims else "ok" if all(n == total[1] for n, _ in claims) else "wrong"
        )
    else:
        if _re(r"fifty|half-century|century|hundred|on \d+|\d+ not out").search(text):
            return None
        ptotal = "not_said"

    event, ev_used = event_label(text, t, m, used)
    if event is None:
        return None
    used |= ev_used

    # Every number left over must be a plain given fact (a clock, a distance) that equals no
    # field's value: one that is wrong, or might be a half-said score or total, can't be decided.
    given = insight._given(m, header) | insight._streaks(m, past)
    values = {float(v) for k, v in s.items() if isinstance(v, int) and k in ("home", "away")}
    values |= {float(s[k]) for k in ("runs", "wickets", "lap") if k in s}
    values |= {total[1]} if total else set()
    if "home" in s:
        values.add(float(abs(s["home"] - s["away"])))
    for i in heard - used:
        if t[i] not in given or t[i] in values:
            return None
    return {"score": score, "leader": lead, "player_total": ptotal, "event": event}


# --- planted errors: one field of a right line changed; the gold is code's label of the result ---


def _spoken(v: int) -> list[str]:
    if v == 0:
        return ["nil", "nothing", "zero"]
    if v < 20:
        return [insight.UNITS[v]]
    if v < 100:
        tens = next(w for w, n in insight.TENS.items() if n == v - v % 10)
        return [tens + (f"-{insight.UNITS[v % 10]}" if v % 10 else "")]
    return []


def _swaps(text: str, v: float, new: float):
    """`text` with one saying of the number v changed to `new`, in each form it might take."""
    v, new = int(v), int(new)
    forms = [(rf"(?<![\d.]){v}(?![\d.])", str(new))]
    forms += [(rf"(?<![-\w]){w}(?![-\w])", _spoken(new)[0]) for w in _spoken(v) if _spoken(new)]
    for pattern, to in forms:
        hit = re.search(pattern, text, re.I)
        if hit:
            to = to.upper() if hit[0].isupper() and len(hit[0]) > 1 else to
            to = to[0].upper() + to[1:] if hit[0][0].isupper() else to
            yield text[: hit.start()] + to + text[hit.end() :]


def _team_swaps(text: str, header: dict):
    """`text` with a team it says leads named as the other team instead."""
    forms = {}
    for s in ("home", "away"):
        w = insight.CLUB_SUFFIX.sub("", header[s]).split() or [header[s]]
        forms[s] = [header[s], " ".join(w), w[-1], " ".join(w[:-1]), w[0]]
    other = {"home": "away", "away": "home"}
    side, names = insight._sides(header)
    for hit in re.finditer(rf"\b({names})(?={insight.LEADS}|{TRAILS}|{WINS})", text, re.I):
        s = side[hit[1].lower()]
        k = next(i for i, f in enumerate(forms[s]) if f.lower() == hit[1].lower())
        yield text[: hit.start()] + forms[other[s]][k] + text[hit.end() :]


def _event_swaps(text: str, m: dict):
    kind, outcome = m["type"], m.get("outcome")
    if m["sport"] == "basketball" and kind == "Field goal":
        hit = (THREE if outcome == "3 points" else TWO_ONLY).search(text) or (
            outcome == "2 points" and FIELD_GOAL.search(text)
        )
        if hit:
            to = "layup" if outcome == "3 points" else "three-pointer"
            yield text[: hit.start()] + to + text[hit.end() :]
    elif m["sport"] == "cricket" and kind in ("Four", "Six"):
        a, b = ("four", "six") if kind == "Four" else ("six", "four")
        for hit in re.finditer(rf"\b{a}\b", text, re.I):
            to = b.upper() if hit[0].isupper() else b.capitalize() if hit[0][0].isupper() else b
            yield text[: hit.start()] + to + text[hit.end() :]
    elif m["sport"] == "football" and kind == "Shot" and outcome != "Goal":
        yield f"GOAL! {text}"  # the live final's miss called as a goal
    elif m["sport"] == "football" and m["detail"].get("card") == "Yellow Card":
        yield re.sub(r"\byellow card\b", "red card", text, count=1, flags=re.I)


def plant(header: dict, m: dict, past: list[dict], text: str, label: dict, field: str):
    """A planted error: `text` with `field` (said right) changed so it is wrong, and every other
    label the same; or None when no change does exactly that."""
    s, total = m["score"], player_total(m, past)
    if field == "score":
        values = [s[k] for k in ("home", "away", "runs", "wickets", "lap") if k in s]
        cands = (c for v in values for c in _swaps(text, v, v + 1))
    elif field == "leader":
        cands = _team_swaps(text, header) if "home" in s else ()
    elif field == "player_total":
        cands = _swaps(text, total[1], total[1] + 2) if total else ()
    else:
        cands = _event_swaps(text, m)
    want = {**label, field: "wrong"}
    return next((c for c in cands if c != text and gold(header, m, past, c) == want), None)
