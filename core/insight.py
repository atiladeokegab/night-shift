"""Colour commentary between the big moments (#130): stat lines that fill each quiet stretch of a
video-mapped replay. An insight is a synthetic "Stat" moment whose detail is built only from the
moments up to the one it follows and the pre-match pack, and it goes through the same commentate
call as any line, so the Mubit task stays one task. Insight lines are kept in the store and reused
by later replays of the same match."""

import math
import re
from collections import Counter

from agent.packs import phase
from core import predict

WORDS_PER_S = 2.7  # a line has likely finished speaking after its words at this rate
PAUSE_S = 2.0  # then this breath before the next insight
CLEAR_S = 6.0  # no insight starts closer than this to the next mapped moment
MAX_CALLS = 160  # new insight calls per replay; cached ones are free
REPLY_EVERY = 3  # every 3rd line in a quiet stretch is the lead replying to the analyst
PER_GAP = 3  # then the stretch ends: two analyst lines and the reply (#162)
# stored insights of another version are never reused (v1 re-called the play, v2 tallied counts)
VERSION = 3
RECENT = 6  # the key moments that count as recent play for momentum


def due_after(t: float, text: str | None) -> float:
    """When the next insight is due after a line said at video time `t`."""
    return t + len(str(text or "").split()) / WORDS_PER_S + PAUSE_S


def _who(m: dict) -> str | None:
    """The moment's main actor: the first role it names (shooter, batter, driver)."""
    return next(iter((m.get("players") or {}).values()), None)


CRICKET_PART = {"batter": "batting", "non_striker": "batting", "bowler": "bowling"}


def _n(count: int, what: str) -> str:
    return f"{count} {what}" + ("" if count == 1 else "s")


def _before(pack) -> str:
    """The span a pack covers, said with every pre-match fact so it never reads as a career."""
    if pack["sport"] == "cricket":  # Cricsheet T20Is from 1 January to the day before
        return "in T20 internationals this year before tonight"
    if "competition 43 " in pack["source"]:  # StatsBomb's FIFA World Cup
        return "at this World Cup before tonight"
    return "this season before tonight"


def _shot_facts(pack, name, tonight, part, over):
    before = _before(pack)
    p, football = pack["players"][name], pack["sport"] == "football"
    mine = [t for t in tonight if t["player"] == name]
    if not (p["attempts"] or mine):  # a keeper's 0 from 0 says nothing
        return []

    def record(made, att):
        if football:
            return f"{_n(made, 'goal')} from {_n(att, 'shot')}"
        return f"made {made} of {_n(att, 'shot')}"

    small = " (a small sample)" if p["attempts"] < predict.SMALL else ""
    pct = f" ({round(100 * p['made'] / p['attempts'])}%)" if p["attempts"] and not football else ""
    out = [
        f"{name} {before}: {record(p['made'], p['attempts'])}{pct} in {p['games']} games{small}."
    ]
    if mine:
        out.append(f"{name} tonight: {record(sum(t['made'] for t in mine), len(mine))}.")
    for z, c in sorted(p["zones"].items(), key=lambda zc: -zc[1]["att"])[:3]:
        if c["att"]:
            out.append(f"{name} {before}, {z}: {record(c['made'], c['att'])}.")
    return out


def _cricket_facts(pack, name, tonight, part, over):
    before = _before(pack)
    p, bat, bowl = pack["players"][name], [], []
    mine = [t for t in tonight if t["batter"] == name]
    if mine:
        bat.append(f"{name} batting tonight: {sum(t['runs'] for t in mine)} off {len(mine)} balls.")
    for ph in sorted(
        ("powerplay", "middle", "death"), key=lambda ph: over is None or ph != phase(over)
    ):
        b = p["batting"].get(ph) or {}
        if b.get("balls"):
            bat.append(
                f"{name} batting in the {ph} overs {before}: {b['runs']} off {b['balls']} balls."
            )
    mine = [t for t in tonight if t["bowler"] == name]
    if mine:
        runs, wickets = sum(t["runs"] for t in mine), sum(bool(t["out"]) for t in mine)
        bowl.append(
            f"{name} bowling tonight: {_n(wickets, 'wicket')} for {_n(runs, 'run')} "
            f"off {_n(len(mine), 'ball')}."
        )
    bw = p["bowling"]
    if bw["balls"]:
        bowl.append(
            f"{name} bowling {before}: {_n(bw['wickets'], 'wicket')} in {bw['balls']} balls."
        )
    if bw.get("economy") is not None:
        bowl.append(f"{name} bowling {before}: economy {bw['economy']} runs an over.")
    return {"batting": bat, "bowling": bowl}.get(part, bat + bowl)


def _f1_facts(pack, name, tonight, part, over):
    before = _before(pack)
    p = pack["players"][name]
    if not p["finishes"]:
        return [f"{name} {before}: no finishes in {_n(p['games'], 'race')}."]
    g = p["avg_gained"]
    return [
        f"{name} {before}: {_n(p['wins'], 'win')} in {_n(p['games'], 'race')}.",
        f"{name} {before}: average finish {p['avg_finish']}.",
        f"{name} {before}: {abs(g):.1f} places {'gained' if g >= 0 else 'lost'} a race "
        "on average from the grid.",
    ]


FACTS = {"cricket": _cricket_facts, "f1": _f1_facts}


def _profiles(pack, past):
    """One short fact per detail, so the analyst has nothing to add up or merge."""
    if not pack:
        return []
    # the latest role each player had: a batter's profile is their batting, a bowler's bowling
    role = {}
    for m in reversed(past):
        for r, n in (m.get("players") or {}).items():
            role.setdefault(n, r)
    # then the rest of the roster: a pre-match record is known before the match starts
    rest = sorted(pack["players"], key=lambda n: -pack["players"][n].get("games", 0))
    tonight = [t for t in pack.get("tonight") or [] if t["idx"] <= past[-1]["idx"]]
    over = None
    if pack["sport"] == "cricket":  # its clock is the over: 11.3; other sports' is "16:15"
        try:
            over = int(str(past[-1].get("clock")).split(".")[0])
        except ValueError:
            pass  # no over to read: the phase is unknown, so the phases keep their usual order
    out = []
    for name in dict.fromkeys([*role, *rest]):
        try:
            key = predict.find(pack, name)
        except KeyError:
            continue
        facts = FACTS.get(pack["sport"], _shot_facts)
        out += facts(pack, key, tonight, CRICKET_PART.get(role.get(name)), over)
    return list(dict.fromkeys(out))


def _odds(pack, past):
    if not pack or pack["sport"] not in predict.SHOTS:
        return []
    what = "goal" if pack["sport"] == "football" else "basket"
    odds = predict.next_score_odds(pack, past, len(past) - 1)
    teams = sorted(odds, key=lambda t: t != past[-1].get("team"))  # this team first
    return [
        f"Chance {r['player']} scores the next {team} {what}: {round(100 * r['p'])}%."
        for team in teams
        for r in odds[team][: predict.TOP]
    ]


def _tallies(pack, past):
    out = []
    for key, label in ((_who, "player"), (lambda m: m.get("team"), "team")):
        for name in dict.fromkeys(key(m) for m in reversed(past)):
            if not name:
                continue
            mine = [m for m in past if key(m) == name]
            if len(mine) < 2:  # one moment is no tally: it would only re-call that play
                continue
            counts = Counter(
                f"{m['type']} ({m['outcome']})" if m.get("outcome") else m["type"] for m in mine
            )
            # basketball keeps the shooter's running total: the key moments' counts beside it
            # never add up to it, and were said as if they did ("eleven twos" for 81)
            pts = [(m.get("detail") or {}).get("player_points") for m in mine]
            pts = [p for p in pts if p is not None] if label == "player" else []
            if pts:
                out.append(f"{name} tonight: {pts[-1]} points so far")
                continue
            said = ", ".join(f"{k} x{v}" for k, v in counts.items())
            out.append(f"{name} tonight, in the key moments so far: {said}")
    return out


def _mark(m: dict):
    """What counts as a change in the score: either side's score, or a wicket in cricket."""
    s = m.get("score") or {}
    return (s.get("home"), s.get("away")) if "home" in s else s.get("wickets")


def _score_story(pack, past):
    m = past[-1]
    s = m.get("score") or {}
    if "home" in s:
        d = s["home"] - s["away"]
        lead = f"the {'home' if d > 0 else 'away'} side leads by {abs(d)}" if d else "level"
        now = f"{s['home']}-{s['away']} (home-away), {lead}"
    elif "runs" in s:
        now = f"{m.get('team')} {s['runs']} for {s['wickets']}"
        if "target" in s:
            now += f", {max(0, s['target'] - s['runs'])} more needed to reach {s['target']}"
    else:
        return []
    changed = [b for a, b in zip(past, past[1:], strict=False) if _mark(a) != _mark(b)]
    if changed:
        c = changed[-1]
        what = f"{c['type']}, {c['outcome']}" if c.get("outcome") else c["type"]
        now += f"; the last change at {c.get('clock')}: {c.get('team')} {what}"
    return [f"Score story: {now}"]


def _momentum(pack, past):
    recent = past[-RECENT:]
    teams = Counter(m["team"] for m in recent if m.get("team"))
    if len(recent) < 2 or not teams:
        return []
    said = ", ".join(f"{t} {n}" for t, n in teams.most_common())
    a, b = (recent[0].get("score") or {}), (recent[-1].get("score") or {})
    if "home" in a and "home" in b:
        said += (
            f"; the score went from {a['home']}-{a['away']} to {b['home']}-{b['away']} (home-away)"
        )
    elif "runs" in a and "runs" in b and recent[0].get("period") == recent[-1].get("period"):
        said += f"; {b['runs'] - a['runs']} runs and {b['wickets'] - a['wickets']} wickets since"
    start = f"period {recent[0].get('period')}, {recent[0].get('clock')}"
    return [f"Momentum, the last {len(recent)} key moments from {start}: {said}"]


def _positions(pack, past):
    s = past[-1].get("score") or {}
    top = [c for c in s.get("top") or [] if c.get("pos")]
    if not top:
        return []
    out = []
    gaps = [
        f"{c['driver']} is P{c['pos']}, {c['gap']} behind the leader."
        for c in top
        if c.get("gap") not in ("", "leader")
    ]
    if s.get("lap"):
        out.append(f"Lap {s.get('lap')} of {s.get('laps')}.")
    out += gaps
    first = {c["driver"]: c["pos"] for c in (past[0].get("score") or {}).get("top") or []}
    for c in top:
        start = (
            f"P{first[c['driver']]}" if first.get(c["driver"]) else f"outside the top {len(first)}"
        )
        out.append(
            f"{c['driver']} P{c['pos']} on lap {s.get('lap')}, from {start} at the first moment"
        )
    return out


KINDS = (
    ("player profile", _profiles),
    ("next to score", _odds),
    ("tally", _tallies),
    ("score story", _score_story),
    ("momentum", _momentum),
    ("positions", _positions),
)


class Gaps:
    """One replay's insights: rotates the kinds, never repeats a detail, reuses stored lines and
    caps new calls."""

    def __init__(self, match_id: str, store):
        self.match_id = match_id
        self.store = store
        self.cached = {
            (i["after_idx"], i["n"]): ln
            for ln in store.all("lines")
            if (i := ln.get("insight") or ln.get("reply"))
            and i.get("match_id") == match_id
            and i.get("v") == VERSION
        }
        self.used: set[str] = set()
        self.turn = 0
        self.opens = 0
        self.calls = 0
        self._pack = None

    def pack(self, m: dict):
        if self._pack is None:
            self._pack = predict.load_pack(m.get("sport", ""), self.match_id) or {}
        return self._pack

    def next_stat(self, past: list[dict], first: bool = False) -> tuple[str, str] | None:
        """The next kind in turn with a detail not said yet in this replay; a stretch's first
        insight takes the pre-match pack's profile or odds when there is a pack, in a turn of its
        own, and the rest of the stretch the other kinds, so two lines a stretch reach them all."""
        opens = first and bool(self.pack(past[-1]))
        start = self.opens if opens else self.turn
        order = [(start + i) % len(KINDS) for i in range(len(KINDS))]
        if self.pack(past[-1]):
            order.sort(key=lambda k: (KINDS[k][0] in ("player profile", "next to score")) != opens)
        for k in order:
            kind, make = KINDS[k]
            for detail in make(self.pack(past[-1]), past):
                if detail not in self.used:
                    if opens:
                        self.opens = k + 1
                    else:
                        self.turn = k + 1
                    return kind, detail
        return None

    def line(
        self,
        past: list[dict],
        n: int,
        video_t: float,
        commentate,
        before: str | None = None,
        recent: list[str] = (),
    ) -> tuple[dict, dict] | None:
        """The n-th line in the quiet stretch after past[-1]: the moment it is said over and its
        stored Line, the cached one, else a new commentate call (an analyst line that comes back
        empty hands the slot to the next kind, once). None ends the stretch. The
        analyst speaks the insights and hears the line before it (`before`); now and then the
        lead replies to the analyst. A line that repeats one of the `recent` ones is never said."""
        m = past[-1]
        if n >= PER_GAP:
            return None
        reply = n % REPLY_EVERY == REPLY_EVERY - 1
        role, speaker = ("reply", "lead") if reply else ("insight", "analyst")
        ln = self.cached.get((m["idx"], n))
        if ln is not None and role in ln:
            said_as = ln[role]
            if not reply and said_as["detail"] in self.used:  # another replay's: never said twice
                return None
            if repeats(ln.get("text") or "", list(recent)):
                return None
        elif self.calls >= MAX_CALLS:
            return None
        else:
            ln = None
            heard = " ".join(str(before or "").split())  # one line: it must not forge a field
            picked = ("reply", heard) if reply else self.next_stat(past, first=n == 0)
            if not picked:
                return None
            said_as = {"kind": picked[0], "detail": picked[1], "heard": heard, "v": VERSION}
        if ln is None:
            for retry in (False, True):
                self.calls += 1
                # the same seam as every line: only moments up to the one followed reach the model
                said = commentate(stat_moment(m, said_as, reply), list(past))
                if said and said.get("text") and not repeats(said["text"], list(recent)):
                    break
                if reply or retry or self.calls >= MAX_CALLS:
                    return None
                self.used.add(said_as["detail"])  # dropped: the next kind gets this slot, once
                picked = self.next_stat(past)
                if not picked:
                    return None
                said_as = {**said_as, "kind": picked[0], "detail": picked[1]}
            key = {"match_id": self.match_id, "after_idx": m["idx"], "n": n}
            ln = self.store.append(
                "lines", {**said, "video_t": video_t, "speaker": speaker, role: {**key, **said_as}}
            )
        if not reply:
            self.used.add(said_as["detail"])
        return stat_moment(m, said_as, reply), ln


RECENT_LINES = 3  # a line is checked against this many before it in the replay
SAME = 0.6  # token Jaccard at or above which two lines say the same thing
# one canonical word per event, so "GOAL! Palmer" and "Palmer scores" share it
EVENT = {
    **dict.fromkeys(
        ("goal", "scores", "scored", "score", "net", "nets", "converts", "finish", "strikes"),
        "goal",
    ),
    **dict.fromkeys(("wicket", "bowled", "caught", "lbw", "stumped"), "wicket"),
    **dict.fromkeys(("six", "sixes"), "six"),
    **dict.fromkeys(("dunk", "slam"), "dunk"),
    **dict.fromkeys(("overtakes", "overtake", "passes"), "overtake"),
}
STOP = set(
    "a an the and or but of to in on at for from with by is are was were be been it its it's "
    "that this these those he she they his her their them there here as so now just still "
    "what who has have had do does did not no yes up down off out over into than then".split()
)


def _words(text: str) -> list[tuple[str, bool]]:
    """Content words, lowercased, events made canonical, each with whether it was capitalised."""
    out = []
    for w in re.findall(r"[A-Za-zÀ-ɏ'’]+|\d+", text):
        low = w.lower().strip("'’")
        if low and low not in STOP:
            out.append((EVENT.get(low, low), w[0].isupper() and low not in EVENT))
    return out


def repeats(text: str, recent: list[str]) -> bool:
    """True when the line nearly repeats one of the recent lines: most of its words, or the same
    name and event (the analyst's "Palmer scores" after the lead's "GOAL! Palmer"). A line with a
    number the other lacks is a new fact, so it stays ("3 shots" after "2 shots", P5 after P8)."""
    words = _words(text)
    toks = {w for w, _ in words}
    names = {w for w, cap in words if cap and not w.isdigit()}
    events = toks & set(EVENT.values())
    for prev in recent[-RECENT_LINES:]:
        before = _words(prev)
        ptoks = {w for w, _ in before}
        if {w for w in toks if w.isdigit()} - ptoks:  # a new number is a new fact
            continue
        if toks and len(toks & ptoks) / len(toks | ptoks) >= SAME:
            return True
        if events & ptoks and names & {w for w, cap in before if cap}:
            return True
    return False


UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
TENS = {
    w: 10 * i
    for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)
}
ORDINALS = {
    w: i
    for i, w in enumerate("first second third fourth fifth sixth seventh eighth ninth".split(), 1)
}


def said(text: str) -> list:
    """The line as words, each number phrase as one float: digits or words ("ninety-six",
    "eighty-first", "one hundred and four"), and scores as spoken ("one twenty-two", "one oh-four").
    A lone "one" is a pronoun as often as a number, and a lone ordinal a place: both stay words."""
    out, cur, words = [], None, []

    def flush():
        nonlocal cur, words
        if cur is not None and words not in (["one"], ["a"]):
            out.append(float(cur))
        else:
            out.extend(words)
        cur, words = None, []

    for w in re.findall(r"\d+(?:\.\d+)?|[a-z]+|[^\w\s'’-]", text.lower()):
        if not w[0].isalnum():  # punctuation ends a number: "for four, ninety-three needed"
            flush()
            continue
        unit = words and len(words) == 1 and words[0] in UNITS[1:10]  # "one" in "one twenty-two"
        if w[0].isdigit():
            flush()
            out.append(float(w))
        elif unit and (w in TENS or w in UNITS[10:] or w == "oh"):
            cur, words = (
                cur * 100 + (TENS.get(w) or (UNITS.index(w) if w != "oh" else 0)),
                [*words, w],
            )
        elif w in TENS:
            if not (cur and cur % 100 == 0):
                flush()
            cur, words = (cur or 0) + TENS[w], [*words, w]
        elif w in UNITS or (w in ORDINALS and cur):
            v = UNITS.index(w) if w in UNITS else ORDINALS[w]
            if not (cur and cur % 10 == 0 and v < 10):
                flush()
            cur, words = (cur or 0) + v, [*words, w]
        elif w == "hundred" and (cur or words == ["a"]):
            cur, words = (cur or 1) * 100, [*words, w]
        elif w == "a":
            flush()
            words = ["a"]
        elif not (w == "and" and cur and cur % 100 == 0):
            flush()
            out.append(w)
    flush()
    return out


def numbers(text: str) -> list[float]:
    """Every number said in the line (see `said`)."""
    return [w for w in said(text) if isinstance(w, float)]


def _given(m: dict, header: dict | None = None) -> set[float]:
    """The numbers this moment's own data gives: score, margin or runs needed, clock (and the
    minute after it, as football says it), period, outcome and details, and the match's stage
    ("Game 6"). Recent play is not here: a number from an earlier moment is how a wide becomes
    "a six"."""
    from agent.commentator import _detail

    s = m.get("score") or {}
    src = " ".join(
        [str(s), str(m.get("clock")), str(m.get("period")), str(m.get("outcome")), _detail(m)]
        + [str((header or {}).get(k, "")) for k in ("competition", "stage")]
    )
    given = set(numbers(src)) | {float(x) for x in re.findall(r"\d+", src)}
    if "home" in s:
        given.add(float(abs(s["home"] - s["away"])))
    if "target" in s:
        given.add(float(max(0, s["target"] - s["runs"])))
    if clock := re.match(r"(\d+):", str(m.get("clock"))):
        minute = int(clock[1])
        given.add(float(minute + 1))
        if m.get("sport") == "basketball" and (sec := re.match(r"\d+:(\d+)", m["clock"])):
            left = minute * 60 + int(sec[1])  # "ninety seconds to play", "one forty-five"
            given |= {float(left), float(minute * 100 + int(sec[1]))}
            given |= {float(f(left / k) * k) for k in (10, 30, 60) for f in (math.floor, math.ceil)}
        if m.get("sport") == "football":  # "the end of the ninety", "four minutes left"
            for full in (45, 90, 105, 120):
                given |= {float(full), float(full - minute), float(full - minute - 1)}
    return given


def _ball(m: dict) -> int:
    over, ball = str(m["clock"]).split(".")
    return int(over) * 6 + int(ball)


def _streaks(m: dict, past: list[dict]) -> set[float]:
    """Counts recent play gives a cricket boundary or wicket: the last k of the moment's own kind
    by its own batter (bowler for a wicket), the balls they span and the runs they made ("three
    sixes in four balls", "18 off six balls"). Only these kinds: a wide must not borrow a six."""
    if m.get("sport") != "cricket" or m.get("type") not in ("Six", "Four", "Wicket"):
        return set()
    role = "bowler" if m["type"] == "Wicket" else "batter"
    who = (m.get("players") or {}).get(role)
    same = [
        p
        for p in past
        if p["idx"] < m["idx"] and p["type"] == m["type"] and p["players"].get(role) == who
    ] + [m]
    out = set()
    for k in range(1, len(same) + 1):
        last = same[-k:]
        runs = sum((p.get("detail") or {}).get("runs_batter") or 0 for p in last)
        out |= {float(k), float(_ball(m) - _ball(last[0]) + 1), float(runs)}
    return out


def wrong_numbers(
    text: str, m: dict, header: dict | None = None, past: list[dict] = ()
) -> list[str]:
    """What a moment's line gets wrong against the moment's own data and the counts its recent
    play gives (`past`: the moments before it); [] when nothing."""
    s, d = m.get("score") or {}, m.get("detail") or {}
    given = _given(m, header) | _streaks(m, past)
    words = said(text)
    heard = [  # "Number 23" names a player, it is no stat
        n
        for prev, n in zip(["", *words], words, strict=False)
        if isinstance(n, float) and prev != "number"
    ]
    wrong = [f"{n:g} is not in the moment" for n in heard if n not in given]
    if "milestone" in d and not set(numbers(d["milestone"])) & set(numbers(text)):
        wrong.append(f"the milestone is unsaid: {d['milestone']}")
    if m.get("sport") == "cricket":
        score = {(s.get("runs"), s.get("wickets")), (s.get("wickets"), s.get("runs"))}
        for a, w, b in zip(words, words[1:], words[2:], strict=False):
            # wickets first ("India two for ten") is a broadcast convention too
            if w == "for" and isinstance(a, float) and isinstance(b, float) and (a, b) not in score:
                wrong.append(f"{a:g} for {b:g} is not runs for wickets")
        left = d.get("balls_left")
        if (
            left is not None
            and left > 1
            and re.search(r"\b(final|last) (ball|delivery)", text, re.I)
        ):
            wrong.append(f"{left} balls are left, not one")
        if (
            "target" in s
            and s["runs"] != s["target"] - 1
            and re.search(r"\b(level|tied|all square)\b", text, re.I)
        ):
            wrong.append("the scores are not level")
    return wrong


def fallback_text(header: dict, m: dict) -> str:
    """A line built only from the moment's data, said when the commentator's numbers stay wrong."""
    from agent.commentator import _score

    who, d = _who(m), m.get("detail") or {}
    said = f"{m['type']}, {m['outcome']}" if m.get("outcome") else m["type"]
    parts = [f"{said}, {who}." if who else f"{said}."]
    extra = d.get("milestone") or (d.get("chase") if "need" not in d.get("chase", "need") else None)
    if extra:
        parts.append(f"{extra[0].upper()}{extra[1:]}.")
    return " ".join([*parts, f"{_score(header, m)}."])


def checked(commentate, moment: dict, history: list[dict]) -> dict | None:
    """A moment's line whose numbers match the moment: regenerated once when they don't, then
    replaced by the line built from the moment's data. A Stat line is the analyst's, and passes."""
    line = commentate(moment, history)
    if not (line and line.get("text")) or moment.get("type") == "Stat":
        return line
    from data.matches import match_header

    try:
        header = match_header(moment["match_id"])
    except KeyError:  # not a bundled match: nothing to build a line from, so it is not checked
        return line
    if not wrong_numbers(line["text"], moment, header, history):
        return line
    again = commentate(moment, history)
    if again and again.get("text") and not wrong_numbers(again["text"], moment, header, history):
        return again
    return {**(again or line), "text": fallback_text(header, moment), "fallback": True}


def stat_moment(m: dict, said_as: dict, reply: bool) -> dict:
    """The synthetic Stat moment an insight or reply is said over: moment m's team and score, with
    the stat itself (or, for the lead's reply, what the analyst just said) as the Event, so the
    model calls the stat rather than m's play again. m's players stay out for the same reason."""
    # m's own detail stays out too; the score line needs these
    keep = {k: v for k, v in (m.get("detail") or {}).items() if k in ("balls_left", "shootout")}
    said_to = {"speaker": "lead" if reply else "analyst", "Partner just said": said_as["heard"]}
    event = (
        f"the lead answers the analyst, who just said: {said_as['heard']}"
        if reply
        else f"{said_as['kind']}: {said_as['detail']}"
    )
    return {**m, "type": "Stat", "outcome": event, "players": {}, "detail": {**keep, **said_to}}


def said_over(line: dict, load_moments) -> list[dict] | None:
    """The moments an insight or reply line was said over, its Stat moment last: so a producer's
    fix goes back with that line's own request, not its moment's. None for a moment's line."""
    said_as = line.get("insight") or line.get("reply")
    if not said_as:
        return None
    moments = load_moments(said_as["match_id"])
    i = next(i for i, m in enumerate(moments) if m["idx"] == said_as["after_idx"])
    return [*moments[: i + 1], stat_moment(moments[i], said_as, "reply" in line)]
