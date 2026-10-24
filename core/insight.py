"""Colour commentary between the big moments (#130): stat lines that fill each quiet stretch of a
video-mapped replay. An insight is a synthetic "Stat" moment whose detail is built only from the
moments up to the one it follows and the pre-match pack, and it goes through the same commentate
call as any line, so the Mubit task stays one task. Insight lines are kept in the store and reused
by later replays of the same match."""

import itertools
import math
import re
from collections import Counter

from agent.packs import phase
from core import predict
from core.fallback import fallback_text  # noqa: F401  checked() says it; tests import it here
from core.voice import NAMES
from data.matches import CLUB_SUFFIX

WORDS_PER_S = 2.7  # a line has likely finished speaking after its words at this rate
PAUSE_S = 2.0  # then this breath before the next insight
CLEAR_S = 6.0  # no insight starts closer than this to the next mapped moment
MAX_CALLS = 160  # new insight calls per replay; cached ones are free
REPLY_EVERY = 3  # every 3rd line in a quiet stretch is the lead replying to the analyst
PER_GAP = 3  # then the stretch ends: two analyst lines and the reply (#162)
# stored insights of another version are never reused (v1 re-called the play, v2 tallied counts,
# v3 opened cold on the stat with no names)
VERSION = 4
OPEN = "cold open"  # the kind of the two lines before the first mapped moment (#221)
OPENING = (  # who says each line of it and what to do: short, so even a read-back fits
    ("lead", "welcome the listener and name the match"),
    ("analyst", "one light line back to your partner"),
)
OPEN_S = 15.0  # the whole cold open is spoken within this
NAME_EVERY = 3  # a line in a stretch uses the partner's name about this often
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

    def __init__(self, match_id: str, store, replay_id: str | None = None):
        self.match_id = match_id
        self.replay_id = replay_id  # stored on its new lines: what this replay spent
        self.store = store
        self.cached = {
            (i["after_idx"], i["n"], "open" in ln): ln
            for ln in store.all("lines")
            if (i := ln.get("insight") or ln.get("reply") or ln.get("open"))
            and i.get("match_id") == match_id
            and i.get("v") == VERSION
        }
        self.used: set[str] = set()
        self.openers: set[tuple[str, ...]] = set()  # the analyst's first words so far (#221)
        self.turn = 0
        self.opens = 0
        self.calls = 0
        self._pack = None
        self._header = None
        self._balls = None

    def balls(self) -> dict[int, dict]:
        if self._balls is None:
            from data.matches import balls

            try:
                self._balls = balls(self.match_id)
            except KeyError:  # not a bundled match: no ball data
                self._balls = {}
        return self._balls

    def header(self) -> dict:
        """The match header, {} for a match that isn't bundled (its numbers are still checked)."""
        if self._header is None:
            from data.matches import match_header

            try:
                self._header = match_header(self.match_id)
            except KeyError:
                self._header = {}
        return self._header

    def pack(self, m: dict):
        if self._pack is None:
            self._pack = predict.load_pack(m.get("sport", ""), self.match_id) or {}
        return self._pack

    def wrong(self, text: str, stat: dict, past: list[dict]) -> list[str]:
        """What an analyst line or reply gets wrong against its stat and the moments before it."""
        return wrong_numbers(text, stat, self.header() or None, past)

    def stale(self, text: str) -> bool:
        """Whether an analyst line opens with the same first words as one before it this replay."""
        return len(o := opener(text)) == OPENER_WORDS and o in self.openers

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
        empty hands the slot to the next kind, once; a line with a wrong number, new or cached, is
        made once more, then dropped). None ends the stretch. The
        analyst speaks the insights and hears the line before it (`before`); now and then the
        lead replies to the analyst. A line that repeats one of the `recent` ones is never said."""
        m = past[-1]
        if n >= PER_GAP:
            return None
        ball = self.balls().get(m["idx"])
        reply = n % REPLY_EVERY == REPLY_EVERY - 1
        role, speaker = ("reply", "lead") if reply else ("insight", "analyst")
        ln = self.cached.get((m["idx"], n, False))
        if n == 0 and ball and (ln or {}).get("insight", {}).get("kind") != "orientation":
            ln = None  # stored before #205: the gap now opens on the ball
        if ln is not None and role in ln:
            said_as = ln[role]
            # another replay's: never said twice; where the ball is may be said again
            if not reply and said_as["kind"] != "orientation" and said_as["detail"] in self.used:
                return None
            if said_as["kind"] != "orientation" and repeats(ln.get("text") or "", list(recent)):
                return None
            if self.wrong(ln.get("text") or "", stat_moment(m, said_as, reply), past):
                ln = None  # stored before the check (or a newer check fails it): made again
            elif not reply and not ln.get("fallback") and self.stale(ln.get("text") or ""):
                ln = None  # opens like an earlier line this replay: made again
        elif self.calls >= MAX_CALLS:
            return None
        else:
            ln = None
            heard = " ".join(str(before or "").split())  # one line: it must not forge a field
            if reply:
                picked = ("reply", heard)
            elif n == 0 and ball:  # a football stretch opens on who has the ball (#205)
                from data.matches import orientation

                picked = ("orientation", orientation(self.header(), past, ball))
            else:  # after the ball, the next line is the stretch's first stat
                picked = self.next_stat(past, first=n == 0 or (n == 1 and bool(ball)))
            if not picked:
                return None
            said_as = {
                "kind": picked[0],
                "detail": picked[1],
                "heard": heard,
                # who said it: the lead's call opens the stretch, the analyst's line before
                "by": "lead" if n % REPLY_EVERY == 0 else "analyst",
                # by position, so a cached line keeps it: about one line in NAME_EVERY
                "named": (m["idx"] + n) % NAME_EVERY == 0,
                "v": VERSION,
            }
            if picked[0] == "orientation":  # said at the ball's time, the latest it reads (A-1.4)
                said_as["clock"] = ball["clock"]
        if ln is None:
            failed = False  # a try had a wrong number or a used opener
            for retry in (False, True):
                if self.calls >= MAX_CALLS:
                    return None
                self.calls += 1
                # the same seam as every line: only moments up to the one followed reach the model
                said = commentate(stat_moment(m, said_as, reply), list(past))
                # where the ball is now is news, though it reads like where it was before; its own
                # check (wrong_orientation, below) falls back to the data's line, never drops it
                fresh = said_as["kind"] == "orientation"
                if said and said.get("text") and (fresh or not repeats(said["text"], list(recent))):
                    # the moment lines' number check: a wrong number gets the same stat once more,
                    # then the line is dropped; an unchecked number is never said
                    stat = stat_moment(m, said_as, reply)
                    right = fresh or not self.wrong(said["text"], stat, past)
                    # the analyst's opener never repeats in a match: asked once more, told which
                    stale = not reply and self.stale(said["text"])
                    if right and (not stale or retry and fresh):  # a ball line falls back below
                        said = {**said, "checked": True, **({"retried": True} if failed else {})}
                        break
                    if retry:
                        return None
                    if stale:
                        said_as = {**said_as, "never open with": " ".join(opener(said["text"]))}
                    failed = True
                    continue
                if reply or retry or self.calls >= MAX_CALLS:
                    return None
                self.used.add(said_as["detail"])  # dropped: the next kind gets this slot, once
                picked = self.next_stat(past)
                if not picked:
                    return None
                said_as = {**said_as, "kind": picked[0], "detail": picked[1]}
                said_as.pop("clock", None)  # a stat is said at its moment's time
            if said_as["kind"] == "orientation" and (
                wrong_orientation(said["text"], m, said_as, self.header(), past)
                or self.stale(said["text"])
            ):
                said = {**said, "text": said_as["detail"], "fallback": True}
            key = {"match_id": self.match_id, "after_idx": m["idx"], "n": n}
            ln = self.store.append(
                "lines",
                {
                    **said,
                    "video_t": video_t,
                    "speaker": speaker,
                    "replay_id": self.replay_id,
                    role: {**key, **said_as},
                },
            )
        if not reply:
            self.used.add(said_as["detail"])
            if not ln.get("fallback"):  # the data's ball line is not the analyst's opener
                self.openers.add(opener(ln["text"]))
        return stat_moment(m, said_as, reply), ln

    def cold_open(
        self, before: list[dict], first: dict, t: float, first_t: float, commentate
    ) -> list[tuple[dict, dict]]:
        """The lines said from video time `t` before the first mapped moment (`first`, at
        `first_t`): the lead welcomes the listener and names the match, the analyst adds one light
        line (#221). Said over the last moment `before` it, else over `first` with no score yet, so
        its play never reaches the request. Cached like the insights; a line, cached or new, is
        said only if it ends a breath before the first call and the open's speech stays within
        OPEN_S, else the open ends there. [(Stat moment, stored Line)] in order."""
        m, history, kickoff = (before[-1], before, False) if before else (first, [], True)
        out, heard, spoken = [], "", 0.0  # spoken: seconds of speech so far, breaths not counted
        for n, (speaker, ask) in enumerate(OPENING):
            lead = speaker == "lead"
            ln = self.cached.get((m["idx"], n, True))
            said_as = (
                ln["open"]
                if ln is not None
                else {
                    "kind": OPEN,
                    "detail": ask,
                    "heard": heard,
                    "by": "lead",
                    "named": True,  # they greet each other by name
                    "kickoff": kickoff,
                    "v": VERSION,
                }
            )
            stat = stat_moment(m, said_as, lead)
            # the moment lines' number check on every open line, cached ones too (#224's for the
            # stretches): a number the match doesn't give is never said; nor a stored answer to a
            # welcome since made again
            if ln is not None and (
                said_as["heard"] != heard or self.wrong(ln.get("text") or "", stat, history)
            ):
                ln, said_as = None, {**said_as, "heard": heard}
                stat = stat_moment(m, said_as, lead)
            if ln is None:
                if t > first_t - CLEAR_S:
                    break
                said = None
                for retry in (False, True):  # a wrong number: asked once more, then the open ends
                    if self.calls >= MAX_CALLS:
                        break
                    self.calls += 1
                    got = commentate(stat, list(history))
                    if got and got.get("text") and not self.wrong(got["text"], stat, history):
                        said = {**got, "checked": True, **({"retried": True} if retry else {})}
                        break
                if said is None:
                    break
                key = {"match_id": self.match_id, "after_idx": m["idx"], "n": n}
                ln = self.store.append(
                    "lines",
                    {
                        **said,
                        "video_t": t,
                        "speaker": speaker,
                        "replay_id": self.replay_id,
                        "open": {**key, **said_as},
                    },
                )
            done = due_after(t, ln.get("text"))
            spoken += done - t - PAUSE_S
            if done > first_t or spoken > OPEN_S:
                break
            if not lead:
                self.openers.add(opener(ln["text"]))
            out.append((stat, {**ln, "video_t": t}))
            heard, t = ln["text"], done
        return out


OPENER_WORDS = 3  # an analyst line's opener: these first words, never twice in a replay (#221)


def opener(text: str) -> tuple[str, ...]:
    """A line's first OPENER_WORDS words, lowercased, without punctuation."""
    return tuple(re.findall(r"[\w'’]+", text.lower())[:OPENER_WORDS])


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


TOKEN = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|[a-z]+|[^\w\s'’-]"


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

    for w in re.findall(TOKEN, text.lower()):
        w = w.replace(",", "") if w[0].isdigit() else w  # "967 of 1,873" is one number
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
            # "one hundred and eleven": a teen after a hundred is part of it too; "ten two-pointers"
            # is ten of them, so a unit joins only a tens word ("ninety-six")
            if not (cur and (words[-1] in TENS and v < 10 or cur % 100 == 0 and v < 20)):
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


def _derived(text: str) -> set[float]:
    """What a stat's own text gives by adding or dividing, as the analyst says it: a tally's counts
    and runs or points summed over any of its kinds ("four shots", "ten boundaries", "28 runs in
    boundaries"), each "a of b" as a percentage, and each score's margin and the change between two
    ("a ten-point hole", "a 21-11 run")."""
    counts, worth = [], []
    for what, n in re.findall(r"(?:\(([^)]*)\))? x(\d+)\b", text):
        counts.append(int(n))
        worth.append(int(n) * int(v[0]) if (v := re.findall(r"\d+", what)) else 0)
    out = set()
    for picks in itertools.product((0, 1), repeat=min(len(counts), 10)):
        out.add(sum(p * c for p, c in zip(picks, counts, strict=False)))
        out.add(sum(p * w for p, w in zip(picks, worth, strict=False)))
    for a, b in re.findall(r"(\d+) of (\d+)", text):
        if int(b):
            out |= {round(100 * int(a) / int(b)), 100 * int(a) // int(b)}
    scores = [(int(a), int(b)) for a, b in re.findall(r"(\d+)-(\d+)", text)]
    out |= {abs(a - b) for a, b in scores}
    for (a, b), (c, d) in itertools.pairwise(scores):
        out |= {abs(c - a), abs(d - b)}
    return {float(n) for n in out}


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


# The model reasoning aloud instead of calling the moment ("Wait—I need to reconsider ..."): only at
# the start of a clause, so "they'll have to wait for the review" is still commentary.
SELF_TALK = re.compile(
    r"(?:^|[.!?,;:—–]\s*)(?:wait\s*[—–-]|wait,\s*i\b|i need to\b|let me\b|reconsider|actually\b)"
    r"|\bthe recent play (?:and|shows|lists)\b|\bthe (?:event parameter|moment given)\b",
    re.I,
)


def talks_to_itself(text: str) -> bool:
    return bool(SELF_TALK.search(text))


LEADS = (  # a claim that a team is in front now; "led" and questions are no claim
    r"\s+(?:(?:are|is|now|still|back|again)\s+){0,2}"
    r"(?:(?:take|takes|retake|retakes|regain|regains|reclaim|reclaims)\s+(?:the|a)\s+lead"
    r"|leads?(?!\s+(?:has|had|is|was|became|of|over|to)\b)|go ahead|goes ahead|ahead"
    r"|in front(?!\s+of\b))\b"
)


def _sides(header: dict) -> tuple[dict[str, str], str]:
    """Each way a line names a team ("Chicago Bulls", "Bulls", "Chicago"; "Brighton" for "Brighton
    & Hove Albion WFC") to its side, and the regex alternation of those names, longest first."""
    words = {s: CLUB_SUFFIX.sub("", header[s]).split() or [header[s]] for s in ("home", "away")}
    names = {
        s: {n.lower() for n in (header[s], " ".join(w), w[-1], " ".join(w[:-1]), w[0]) if n}
        for s, w in words.items()
    }
    shared = names["home"] & names["away"]  # "Manchester" names neither side of a derby
    side = {n: s for s, ns in names.items() for n in ns - shared}
    return side, "|".join(re.escape(n) for n in sorted(side, key=len, reverse=True))


def _false_lead(text: str, m: dict, header: dict) -> list[str]:
    """Each team a line says leads, when it doesn't: "Chicago Bulls take the lead" at 85-86."""
    from data.matches import leader

    side, names = _sides(header)
    claims = {
        side[c.lower()]
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if not sentence.rstrip().endswith("?")
        for c in re.findall(rf"\b({names}){LEADS}", sentence, re.I)
    }
    return [f"{header[s]} do not lead" for s in sorted(claims) if s != leader(m)]


MARGIN = (  # "Bulls down three", "Utah up by five", "the Jazz lead by two"; not "lead 86-85"
    r"\s+(?:(?:are|is|now|still)\s+)*(?:down|up|leads?|trails?|ahead|behind)\s+(?:by\s+)?"
    r"(\d+|[a-z]+(?:-[a-z]+)?)\b(?!\s*[-–]\s*\w|\s+(?:to|seconds?|minutes?|left)\b)"
)


def _wrong_margin(text: str, m: dict, header: dict) -> list[str]:
    """Each margin a line gives a team that is not the score difference (or, once a shootout's
    goals are level, the shootout's)."""
    s, so = m["score"], m["detail"].get("shootout")
    margins = {float(abs(s["home"] - s["away"]))}
    if so:
        margins.add(float(abs(so["home"] - so["away"])))
    _, names = _sides(header)
    wrong = []
    for hit in re.finditer(rf"\b(?:{names}){MARGIN}", text, re.I):
        # the whole spoken number, then what follows it: "lead one hundred and two to ninety-three"
        # is a score, as is "trail 69, 53"
        if len(said(hit[1])) > 1:  # "lead two-one" is a score
            continue
        n, *after = said(text[hit.start(1) : hit.start(1) + 48]) or [None]
        n = 1.0 if n == "one" else n
        if isinstance(n, float) and not (
            after and (isinstance(after[0], float) or after[0] in ("to", "one"))  # "lead two, one"
        ):
            if n not in margins:
                wrong.append(f"{n:g} is not the margin ({min(margins):g})")
    return wrong


LAST_BALL = re.compile(r"\blast ball\b", re.I)


def wrong_numbers(
    text: str, m: dict, header: dict | None = None, past: list[dict] = ()
) -> list[str]:
    """What a moment's line gets wrong against the moment's own data and the counts its recent
    play gives (`past`: the moments before it); [] when nothing."""
    s, d = m.get("score") or {}, m.get("detail") or {}
    given = _given(m, header) | _streaks(m, past)
    if m.get("type") == "Stat":  # an analyst line: its stat, said just after past[-1]
        given |= _derived(str(m.get("outcome")))
        if past:  # "two free throws" on 2 of 2
            given |= _given(past[-1], header)
    words = said(text)
    heard = [  # "Number 23" names a player, it is no stat
        n
        for prev, n in zip(["", *words], words, strict=False)
        if isinstance(n, float) and prev != "number"
    ]
    wrong = [f"{n:g} is not in the moment" for n in heard if n not in given]
    if talks_to_itself(text):
        wrong.append("the line talks to itself")
    if "home" in s and header:
        wrong += _false_lead(text, m, header) + _wrong_margin(text, m, header)
    if "milestone" in d and not set(numbers(d["milestone"])) & set(numbers(text)):
        wrong.append(f"the milestone is unsaid: {d['milestone']}")
    if m.get("sport") == "cricket":
        score = {(s.get("runs"), s.get("wickets")), (s.get("wickets"), s.get("runs"))}
        for a, w, b, unit in zip(words, words[1:], words[2:], [*words[3:], ""], strict=False):
            # wickets first ("India two for ten") is a broadcast convention too; "a six for 6 runs"
            # is no score
            if (
                w == "for"
                and isinstance(a, float)
                and isinstance(b, float)
                and (a, b) not in score
                and unit not in ("run", "runs")
            ):
                wrong.append(f"{a:g} for {b:g} is not runs for wickets")
        left = d.get("balls_left")
        if (
            left is not None
            and left > 1
            and re.search(r"\b(final|last) (ball|delivery)", text, re.I)
            and not LAST_BALL.search(str(m.get("outcome")))  # a tally's "Last ball (2 runs)"
        ):
            wrong.append(f"{left} balls are left, not one")
        if (
            "target" in s
            and s["runs"] != s["target"] - 1
            and re.search(r"\b(level|tied|all square)\b", text, re.I)
        ):
            wrong.append("the scores are not level")
    return wrong + wrong_event(text, m)  # so checked() regenerates a wrong event too


# A football line that calls the wrong kind of event, worse than a wrong number: a miss called as a
# goal, a booking as a penalty, a shot wide as saved (the live final's idx 18, 28, 59 and 63).
# "levels it" is the kick that made it level; "level at three all" and "two to level it" are not
LEVELS = r"equali[sz]e[sd]?|(?<!to )level(?:s|led)? (?:it|things|the score)"
# present tense only ("who scored twice" recalls a goal), never "the scores"; GOAL in capitals only
GOAL_WORDS = re.compile(
    rf"(?i:\b(?:(?<!the )scores(?! level| are)|nets|{LEVELS})\b"
    r"|\bmakes? it (?:\d|one|two|three|four|five))|\bGOAL\b"
)
LEVEL = re.compile(rf"\b(?:{LEVELS})\b", re.I)
PENALTY = re.compile(r"\b(?:penalty|spot[- ]kick)\b", re.I)  # "penalties" is the shootout
SAVED = re.compile(r"\b(?:save|saves|saved|saving)\b", re.I)
# how a shot that is no goal ended: a line with none of these is said like a goal, or says nothing
ENDED = re.compile(
    r"\b(?:wide|over|high|miss\w*|off (?:the )?target|off t|away|drifts?|sails?|skie[sd]|wayward|"
    r"post|bar|save\w*|stands? tall|denie[sd]|den(?:y|ies)|keeps? it out|stops?|block\w*|"
    r"parrie[sd]|claims?|gathers?|equal to|not|no|but|chance|close|just|inches|"
    r"tr(?:y|ies)|attempt|effort)\b",
    re.I,
)


# Phrases only: a bare "three", "six" or "tie" is mostly a number or a score ("three forty-four to
# play", "Pakistan six for one"). A wrong leader and the model talking to itself are wrong_numbers'.
THREE = re.compile(
    r"\b(?:three[- ]pointer|3[- ]pointer|from (?:deep|(?:way )?downtown|beyond the arc|long range)"
    r"|beyond the arc)\b(?!\s+earlier)",  # "who hit from deep earlier" recalls a past three
    re.I,
)
TIE = re.compile(
    r"\b(?:a tie|it's a tie|their tie|the tie|tie it|tied (?:the match|it)|match is tied"
    r"|level the scores?|levels? it|level (?:with|on)(?! the (?:\w+[ -])?rate)|scores? level"
    r"|super over"
    r"|matched \w+'s (?:total|score)|all square)\b",
    re.I,
)
# capitals are a shout; a six wanted (WANTED_SIX) or a score, "160 for SIX", is no six hit
SIX = re.compile(r"(?i:\b(?:a|the|another) six\b|\bmaximum\b)|(?<!\d [Ff][Oo][Rr] )\bSIX\b")
# "need a six", "looking for a six"; "find a six" only asked or wished ("can he find a six?",
# "unless he finds a six"): "Kohli finds a six!" is one hit
WANTED_SIX = re.compile(
    r"\b(?:needs?|needed|needing|look(?:ing)? for) (?:a|another) six\b"
    r"|\b(?:unless|if|can|could|to)\b[^.!?]*?\bfind(?:s|ing)? (?:a|another) six\b"
    r"|\bfind(?:s|ing)? (?:a|another) six\b[^.!?]*\?",
    re.I,
)
HOW_OUT = {
    "stumped": re.compile(r"\bstump(?:ed|ing)\b", re.I),
    "lbw": re.compile(r"\blbw\b|\bleg before\b", re.I),
    "run out": re.compile(r"\brun[- ]out\b(?! of)", re.I),  # "bowled" also names the bowler
}


def _wrong_basketball(text: str, m: dict) -> list[str]:
    if m.get("outcome") == "2 points" and THREE.search(text):
        return ["a three is called, but the shot was a two"]
    return []


def _wrong_cricket(text: str, m: dict) -> list[str]:
    d, kind = m.get("detail") or {}, m.get("type")
    wrong = []
    if " win " in f" {d.get('chase', '')} " and TIE.search(text):  # "India win by 4 wickets"
        wrong.append(f"a tie is called, but {d['chase']}")
    six = SIX.search(WANTED_SIX.sub("", text))
    if kind in ("Chase", "Last ball") and m.get("outcome") != "6 runs" and six:
        wrong.append(f"a six is called, but the ball was {m.get('outcome')}")
    if kind == "Wicket":
        out = m.get("outcome")
        wrong += [
            f"{how} is called, but the wicket was {out}"
            for how, said in HOW_OUT.items()
            if how != out and said.search(text)
        ]
    return wrong


def _team_scores(text: str, m: dict) -> bool:
    """ "Argentina score again", "France scored": a team's goal, which GOAL_WORDS' "scores" misses.
    Not "Argentina's score" or "Argentina score is two"."""
    from data.matches import match_header

    try:
        _, names = _sides(match_header(m["match_id"]))
    except KeyError:  # not a bundled match: no team names to look for
        return False
    return bool(
        re.search(
            rf"\b(?:{names})\s+(?:(?:have|has|just|now)\s+)?score[sd]?\b"
            r"(?!\s+(?:level|is|are|was|twice|once|none|nothing))",  # "scored twice": a recap
            text,
            re.I,
        )
    )


def wrong_event(text: str, m: dict) -> list[str]:
    """What a line says happened that the moment's type and outcome deny; [] if nothing."""
    if m.get("type") == "Stat":  # a reply over a stat recalls play
        return []
    if m.get("sport") == "basketball":
        return _wrong_basketball(text, m)
    if m.get("sport") == "cricket":
        return _wrong_cricket(text, m)
    if m.get("sport") != "football":
        return []
    d, s = m.get("detail") or {}, m.get("score") or {}
    goal = m.get("type") == "Shot" and m.get("outcome") == "Goal"
    wrong = []
    called = GOAL_WORDS.search(text) or _team_scores(text, m)
    if not goal and m.get("type") != "Full time" and called:  # full time recaps
        wrong.append(f"a goal is called, but the moment is {m['type']}, {m.get('outcome')}")
    tally = d.get("shootout") or s
    if goal and LEVEL.search(text) and tally.get("home") != tally.get("away"):
        # a shootout kick levels only the shootout: the match was level before it
        wrong.append(
            f"the shootout is {tally['home']}-{tally['away']} after this kick, not level"
            if "shootout" in d
            else "the scores are not level after this goal"
        )
    gives_one = "own box" in d.get("where", "") or "shootout" in d  # a foul there can be one
    if "card" in d and not gives_one and PENALTY.search(text):
        wrong.append(f"a penalty is called, but the moment is a {d['card']}")
    if m.get("outcome") in ("Off T", "Wayward") and SAVED.search(text):
        wrong.append("a save is called, but the shot was off target")
    if m.get("type") == "Shot" and not goal and not ENDED.search(text):
        wrong.append(f"the line never says how the shot ended: {m.get('outcome')}")
    return wrong


def checked(commentate, moment: dict, history: list[dict]) -> dict | None:
    """A moment's line whose numbers match the moment: regenerated once when they don't, then
    replaced by the line built from the moment's data. A Stat line is the analyst's: `Gaps.line`
    checks it.
    Every line the check saw is marked `checked` (#204). An accepted retry carries the rejected
    first try as `rejected` and is marked `retried`; a fallback keeps the failed try as `tried` and
    the check's reasons as `wrong`, for the producer's review queue."""
    line = commentate(moment, history)
    if not (line and line.get("text")) or moment.get("type") == "Stat":
        return line
    from data.matches import match_header

    try:
        header = match_header(moment["match_id"])
    except KeyError:  # not a bundled match: nothing to build a line from, so it is not checked
        return line
    if not wrong_numbers(line["text"], moment, header, history):
        return {**line, "checked": True}
    again = commentate(moment, history)
    if again and again.get("text"):
        if not (wrong := wrong_numbers(again["text"], moment, header, history)):
            # the replay corrects the recorded first try with it
            return {**again, "rejected": line, "retried": True, "checked": True}
    else:  # nothing usable the second time: the first try is the one the producer fixes
        again, wrong = line, wrong_numbers(line["text"], moment, header, history)
    tried = {"tried": again["text"], "wrong": wrong, "checked": True}
    return {**again, "text": fallback_text(header, moment), "fallback": True, **tried}


# where the ball goes next is not in the data: an orientation line never says it
NEXT = re.compile(r"\b(?:will|looking to|looks? to|about to|going to|set to|heading)\b|'ll\b", re.I)


def wrong_orientation(
    text: str, m: dict, said_as: dict, header: dict, past: list[dict]
) -> list[str]:
    """What an orientation line (#205) gets wrong: a number its stat and moment m don't give, a
    false leader, a goal called (the ball in play between key moments is no event), or where the
    ball goes next."""
    stat = stat_moment(m, said_as, False)
    wrong = wrong_numbers(text, stat, header, past)
    wrong += wrong_event(text, {**stat, "type": "Possession", "outcome": ""})
    return wrong + [f"says what comes next: {hit[0]}" for hit in NEXT.finditer(text)]


def wrong_answer(answer: dict, question: str, past: list[dict], lines: list[dict]) -> list[str]:
    """Each number an Ask answer says that nothing it was given gives: the moments so far (and
    what they add up to, as a tally does), the lines heard, the question and its tools' outputs."""
    from data.matches import match_header

    try:
        header = match_header(past[-1]["match_id"])
    except KeyError:
        header = None
    tools = [str(t.get("output")) for t in answer.get("tool_calls") or []]
    src = " ".join([question, *(ln.get("text") or "" for ln in lines), *tools])
    given = set(numbers(src)) | {float(x) for x in re.findall(r"\d+", src)} | _derived(src)
    for p in past:
        given |= _given(p, header)
    now = _given(past[-1], header)  # "how many more to pass Wilt's 100?": 100 less Kobe's 43
    given |= {abs(q - n) for q in numbers(question) for n in now}
    for key in (_who, lambda p: p.get("team")):
        for name in {key(p) for p in past} - {None}:
            mine = Counter(f"{p['type']} ({p.get('outcome')})" for p in past if key(p) == name)
            given |= _derived(", ".join(f"{k} x{v}" for k, v in mine.items()))
    return [f"{n:g} is not in the match so far" for n in numbers(answer["text"]) if n not in given]


# "Messi hasn't scored yet" with his penalty in (#236). Not one with a time window, "hasn't scored
# since the 81st minute", "no goal for Messi in extra time", nor "again", "from open play" or "was
# not the only goal"; "in this final" is caught
NOT_SCORED = re.compile(
    r"\b(?:hasn't|has not|hadn't|had not|yet to|still to|not|never|no)\s+"
    r"(?:(?!only\b)\w+\s+){0,2}?(?:scor\w*|goals?|netted|found the net)\b"
    r"(?!\s+(?:again|from open play|(?:for\s+\w+(?:\s+\w+)?\s+)?(?:yet\s+)?(?:since"
    r"|in\s+(?:the\s+)?(?:extra[- ]time|(?:first|second) half|(?:penalty )?shootout)))\b)",
    re.I,
)
# a goal said to have happened: "his second", "Mbappé's brace", "completes a hat-trick"; never
# "one away from a hat-trick"
NTH = re.compile(
    r"\bhis (first|second|third|fourth)\b(?=\s*(?:goal|of\b|[.!?,]|$))"
    r"|(?:\bhis|['’]s)\s+(brace|hat[- ]trick)\b"
    r"|\b(?:scor\w*|got|gets|complet\w*|grabs?|grabbed|nets?|netted)\s+(?:a|his)\s+"
    r"(brace|hat[- ]trick)\b",
    re.I,
)
NTH_GOAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "brace": 2}
HALVES_SAID = {"second half": 2, "first half of extra time": 3, "second half of extra time": 4}
NOW_IN = r"\b(?:we're|we are|it's|it is|deep|now|already)\s+(?:\w+\s+)?(?:in|into)\s+the\s+"


def _named_before(named: list[tuple[int, str]], at: int) -> str | None:
    """The player named last before `at`, whose claim it is: "Messi scored, but Di María hasn't"."""
    return next((name for start, name in reversed(named) if start < at), None)


def wrong_claims(text: str, past: list[dict]) -> list[str]:
    """What a football answer says that the numbers check can't see: a player's goals so far, each
    claim tied to the player named last before it, and that the match is now in a half it hasn't
    reached ("we're deep in the second half of extra time" at 105:41; never "in the second half
    they need to come out stronger")."""
    from agent.commentator import goals_so_far

    m = past[-1]
    if m.get("sport") != "football":
        return []
    wrong = [
        f"the match has not reached the {part}"
        for part, period in HALVES_SAID.items()
        if period > m.get("period", period) and re.search(rf"{NOW_IN}{part}\b", text, re.I)
    ]
    goals = Counter(p["players"].get("shooter") for p in goals_so_far(past) if p.get("players"))
    names = {n for p in past for n in (p.get("players") or {}).values() if isinstance(n, str)}
    surnames = Counter(n.split()[-1] for n in names)
    said = {n: n if surnames[n.split()[-1]] > 1 else n.split()[-1] for n in names}  # two Martínez
    for clause in re.split(r"(?<=[.!?;])\s+", text):  # a clause each: "Messi; Mbappé's brace"
        named = sorted(
            (hit.start(), name)
            for name in names
            for hit in re.finditer(rf"\b{re.escape(said[name])}\b", clause)
        )

        for hit in NOT_SCORED.finditer(clause):
            # "No goal for Messi yet": with no one named before it, the player it is "for"
            after = re.match(r"\s+for\s+", clause[hit.end() :])
            at = hit.end() + after.end() if after else -1
            for_whom = next((name for start, name in named if start == at), None)
            if (name := _named_before(named, hit.start()) or for_whom) and goals[name]:
                wrong.append(f"{name} has scored {goals[name]} so far")
        for hit in NTH.finditer(clause):
            n = NTH_GOAL.get(next(g for g in hit.groups() if g).lower(), 3)
            if (name := _named_before(named, hit.start())) and n > goals[name]:
                wrong.append(f"{name} has scored {goals[name]} so far, not {n}")
    return wrong


def checked_answer(ask, question: str, past: list[dict], lines: list[dict]) -> dict | None:
    """An Ask answer whose numbers (wrong_answer) and goals and half (wrong_claims) match what it
    was given: asked again once with the reasons when they don't, then the status from the data
    and the goals so far (#236), so a viewer never hears an unchecked answer. None, the calm
    off-air line, when the model gives nothing or the match has no data to say instead."""
    from agent.commentator import goals_so_far
    from agent.status import fallback_text as status_text
    from data.matches import match_header

    wrong: list[str] = []
    for retry in (False, True):
        answer = ask(question, past, lines, **({"wrong": wrong} if retry else {}))
        if answer is None:
            return None
        wrong = wrong_answer(answer, question, past, lines) + wrong_claims(answer["text"], past)
        if not wrong:
            return {**answer, "checked": True, **({"retried": True} if retry else {})}
    try:
        text = status_text(match_header(past[-1]["match_id"]), past[-1])
    except KeyError:
        return None
    goals = [
        f"{p['players'].get('shooter')} after {int(p['clock'].split(':')[0])} minutes"
        for p in goals_so_far(past)
        if p.get("players")
    ]
    text += f" Goals: {'; '.join(goals)}." if goals else ""
    tried = {"tried": answer["text"], "wrong": wrong, "checked": True}
    return {**answer, "text": text, "fallback": True, **tried}


def stat_moment(m: dict, said_as: dict, reply: bool) -> dict:
    """The synthetic Stat moment an insight or reply is said over: moment m's team and score, with
    the stat itself (or, for the lead's reply, what the analyst just said) as the Event, so the
    model calls the stat rather than m's play again. m's players stay out for the same reason."""
    # m's own detail stays out too; the score line needs these
    keep = {k: v for k, v in (m.get("detail") or {}).items() if k in ("balls_left", "shootout")}
    me, partner = ("lead", "analyst") if reply else ("analyst", "lead")
    by = said_as.get("by") or partner  # who said `heard`: before v4, always the partner
    said_to = {  # the names reach only this unrecorded request, never the lead's moment prompt
        "speaker": me,
        "you are": NAMES[me],
        "partner": f"{NAMES[partner]}, the {partner}",
        "call partner by name": "yes" if said_as.get("named") else "no",
        f"{NAMES[by]} just said": said_as["heard"],
        **({"never open with": said_as["never open with"]} if "never open with" in said_as else {}),
    }
    event = (
        f"the lead answers the analyst, who just said: {said_as['heard']}"
        if reply and said_as.get("kind") != OPEN
        else f"{said_as['kind']}: {said_as['detail']}"
    )
    score = m.get("score") or {}
    if said_as.get("kickoff"):  # the cold open before any play: no count from the first moment
        # shortcut: a chase's target and an F1 order stay; zero them if a video starts there
        score = {k: 0 if k in ("home", "away", "runs", "wickets") else v for k, v in score.items()}
    clock = said_as.get("clock", m.get("clock"))  # an orientation line's is the ball's (#205)
    return {
        **m,
        "clock": clock,
        "type": "Stat",
        "outcome": event,
        "players": {},
        "score": score,
        "detail": {**keep, **said_to},
    }


def said_over(line: dict, load_moments) -> list[dict] | None:
    """The moments an insight or reply line was said over, its Stat moment last: so a producer's
    fix goes back with that line's own request, not its moment's. None for a moment's line."""
    said_as = line.get("insight") or line.get("reply") or line.get("open")
    if not said_as:
        return None
    moments = load_moments(said_as["match_id"])
    i = next(i for i, m in enumerate(moments) if m["idx"] == said_as["after_idx"])
    stat = stat_moment(moments[i], said_as, line.get("speaker") == "lead")
    return [stat] if said_as.get("kickoff") else [*moments[: i + 1], stat]
