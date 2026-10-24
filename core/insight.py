"""Colour commentary between the big moments (#130): stat lines that fill each quiet stretch of a
video-mapped replay. An insight is a synthetic "Stat" moment whose detail is built only from the
moments up to the one it follows and the pre-match pack, and it goes through the same commentate
call as any line, so the Mubit task stays one task. Insight lines are kept in the store and reused
by later replays of the same match."""

import itertools
import logging
import math
import random
import re
import uuid
from collections import Counter

from agent.packs import phase
from core import predict
from core.fallback import fallback_text  # noqa: F401  checked() says it; tests import it here
from core.voice import NAMES, intensity
from data.matches import CLUB_SUFFIX

log = logging.getLogger(__name__)

WORDS_PER_S = 2.7  # a line has likely finished speaking after its words at this rate
PAUSE_S = 2.0  # then this breath before the next line of the cold open
# between two voices in a stretch, short, so the next is due as this one ends; the page holds a line
# due early until the voice on air finishes (#288)
TURN_S = 0.3
MAX_CALLS = 240  # new insight calls per replay, enough to fill the longest video; cached are free
# after the lead's call the voices alternate, never one twice in a row (#288), voice after voice
# until the next mapped moment (#297): a line starts only with room for MIN_WORDS before it
MIN_WORDS = 8  # about 3 s: a shorter leftover stays quiet
MISSES = 1  # dropped lines a stretch survives: that voice tries again on its next turn
# stored insights of another version are never reused (v1 re-called the play, v2 tallied counts,
# v3 opened cold on the stat with no names, v4 gave the analyst two lines in a row, v5 named by
# position and stopped after three lines)
VERSION = 6
COMEBACK_WORDS = 10  # the lead's comeback is asked to keep to this many words
OPEN = "cold open"  # the kind of the two lines before the first mapped moment (#221)
OPENING = (  # who says each line of it and what to do: short, so even a read-back fits
    (
        "lead",
        "welcome the listener and set the scene: the two teams, the competition and its stage",
    ),
    ("analyst", "one light line back to your partner"),
)
OPEN_WORDS = 12  # agent/analyst.md's most for a cold open line; less when less fits (#297)
# how often a stretch line may use the partner's name: the lead's comeback, the analyst (#297)
NAMED = {"lead": 1 / 3, "analyst": 1 / 4}
ANALYST_WORDS = 18  # the analyst's line is asked to keep to this many words
CUT_WORDS = 22  # a stretch line longer than this is cut at its last full sentence that fits
RECENT = 6  # the key moments that count as recent play for momentum


def due_after(t: float, text: str | None, pause: float = PAUSE_S) -> float:
    """When the next insight is due after a line said at video time `t`."""
    return t + len(str(text or "").split()) / WORDS_PER_S + pause


def room(t: float, end: float | None) -> float:
    """The words a line started at video time `t` can say and still end a turn before `end`."""
    return math.inf if end is None else (end - TURN_S - t) * WORDS_PER_S


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
    if "competition 43 " in pack.get(
        "source", ""
    ):  # StatsBomb World Cup; a graph-only pack has none
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


def _look_back(pack, past):
    """The moments before the one just called, newest first: the booth looks back at one (#297)."""
    out = []
    for m in reversed(past[:-1]):
        what = f"{m['type']}, {m['outcome']}" if m.get("outcome") else m["type"]
        by = f" by {_who(m)}" if _who(m) else ""
        out.append(f"Earlier, at {m.get('clock')}: {m.get('team')} {what}{by}")
    return out


def _form(pack, past):
    """Each team's form and their head-to-head before tonight, from the graph."""
    from data.matches import match_header

    try:
        h = match_header(past[-1]["match_id"])
    except KeyError:
        return []
    if not (h.get("home") and h.get("away")):  # a race has no two sides
        return []
    return predict.form_texts(h["sport"], h["home"], h["away"], h.get("date", ""))


KINDS = (
    ("player profile", _profiles),
    ("next to score", _odds),
    ("tally", _tallies),
    ("score story", _score_story),
    ("look back", _look_back),
    ("momentum", _momentum),
    ("positions", _positions),
    ("form", _form),
)
# what each kind is about, told to the analyst in the user message, so the lines never loop (#297)
ANGLES = {
    "player profile": "a player",
    "next to score": "what to watch for next",
    "tally": "a player",
    "score story": "the game state",
    "look back": "look back at an earlier moment",
    "momentum": "the game state",
    "positions": "the game state",
    "form": "the teams' form before tonight",
}


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
        self.focus: str | None = None  # the player a quiet stretch's conversation is about (#378)
        self.skip: str | None = None  # a kind whose line was just dropped: the slot goes to another
        self.focused: set[str] = set()  # players already talked about this replay
        self.asked = None  # what the lead's last comeback asked the analyst about
        self.calls = 0
        self.overran = False  # the last line was dropped for running into the next moment (#297)
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
            self._pack = predict.pack(m.get("sport", ""), self.match_id) or {}
        return self._pack

    def wrong(self, text: str, stat: dict, past: list[dict]) -> list[str]:
        """What an analyst line or reply gets wrong against its stat and the moments before it."""
        return wrong_numbers(text, stat, self.header() or None, past)

    def stale(self, text: str) -> bool:
        """Whether an analyst line opens with the same first words as one before it this replay."""
        return len(o := opener(text)) == OPENER_WORDS and o in self.openers

    def next_stat(
        self, past: list[dict], first: bool = False, prefer: str | None = None
    ) -> tuple[str, str] | None:
        """The next kind in turn with a detail not said yet in this replay; a stretch's first
        insight takes the pre-match pack's profile or odds when there is a pack, in a turn of its
        own, and the rest of the stretch the other kinds, so two lines a stretch reach them all."""
        if hit := self.about_one_player(past, first):
            return hit
        opens = first and bool(self.pack(past[-1]))
        start = self.opens if opens else self.turn
        order = [(start + i) % len(KINDS) for i in range(len(KINDS))]
        if self.pack(past[-1]):
            order.sort(key=lambda k: (KINDS[k][0] in ("player profile", "next to score")) != opens)
        order.sort(key=lambda k: KINDS[k][0] != prefer)  # what the lead just asked about, first
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

    def about_one_player(self, past: list[dict], first: bool) -> tuple[str, str] | None:
        """A quiet stretch's conversation (#378): the stretch's first stat picks a player who has
        not had one yet and who has at least two facts, and the turns that follow stay on that
        player, one fact each, until the facts run out. None leaves it to the rotating kinds."""
        pack = self.pack(past[-1])
        if not pack:
            return None
        if first:
            self.focus = None
        # every kind's facts that name the player, so a stretch has enough to stay on them
        pool = [
            (kind, d)
            for kind, make in (
                ("player profile", _profiles),
                ("tally", _tallies),
                ("next to score", _odds),
            )
            for d in make(pack, past)
            if d not in self.used and kind != self.skip
        ]
        by = {
            n: [(k, d) for k, d in pool if d.startswith(n + " ") or f" {n} " in d]
            for n in pack["players"]
        }
        if self.focus is None:
            fresh = {n: fs for n, fs in by.items() if len(fs) >= 2 and n not in self.focused}
            self.focus = max(fresh, key=lambda n: len(fresh[n]), default="")  # the longest talk
            self.focused.add(self.focus)
        if self.focus and by.get(self.focus):
            return by[self.focus][0]
        self.focus = ""  # out of facts: the rest of the stretch rotates, it never moves to another
        return None

    def peek(self, past: list[dict], first: bool = False) -> tuple[str, str] | None:
        """The stat next_stat would pick now, without taking its turn."""
        turn, opens, focus, done = self.turn, self.opens, self.focus, set(self.focused)
        try:
            return self.next_stat(past, first)
        finally:
            self.turn, self.opens, self.focus, self.focused = turn, opens, focus, done

    def line(
        self,
        past: list[dict],
        n: int,
        video_t: float,
        commentate,
        before: str | None = None,
        recent: list[str] = (),
        end: float | None = None,
        orient: bool = True,
    ) -> tuple[dict, dict] | None:
        """The n-th line in the quiet stretch after past[-1]: the moment it is said over and its
        stored Line, the cached one, else a new commentate call (an analyst line that comes back
        empty hands the slot to the next kind, once; a line with a wrong number, new or cached, is
        made once more, then dropped). None ends the stretch. The
        analyst speaks the insights and the lead comes back to them in turn, each hearing the line
        before it (`before`). The lead's comeback is told what the analyst's next stat is about when
        that line fits before `end`, the next mapped moment, so a question from the lead gets its
        answer. A line that repeats one of the `recent` ones, or echoes a phrase from one, is never
        said; nor one that would not end before `end` (#297). `orient`: a football stretch opens on
        who has the ball."""
        m = past[-1]
        self.overran = False
        reply = n % 2 == 1
        most = int(min(COMEBACK_WORDS if reply else ANALYST_WORDS, room(video_t, end)))
        ball = self.balls().get(m["idx"]) if orient else None
        role, speaker = ("reply", "lead") if reply else ("insight", "analyst")
        heard = " ".join(str(before or "").split())  # one line: it must not forge a field
        ln = self.cached.get((m["idx"], n, False))
        if n == 0 and ball and (ln or {}).get("insight", {}).get("kind") != "orientation":
            ln = None  # stored before #205: the gap now opens on the ball
        # the lead's call is made again each replay, so the first line's reaction to it is kept; a
        # later line that answered another line is made again
        if ln is not None and role in ln and n and ln[role].get("heard") != heard:
            ln = None
        if ln is not None and role in ln:
            said_as = ln[role]
            # another replay's: never said twice; where the ball is may be said again
            if not reply and said_as["kind"] != "orientation" and said_as["detail"] in self.used:
                return None
            if said_as["kind"] != "orientation" and repeats(ln.get("text") or "", list(recent)):
                return None
            if said_as["kind"] != "orientation" and echoes(ln.get("text") or "", list(recent)):
                ln = None  # says a phrase a recent line said: made again
            if self.wrong(ln.get("text") or "", stat_moment(m, said_as, reply), past):
                ln = None  # stored before the check (or a newer check fails it): made again
            elif not reply and not ln.get("fallback") and self.stale(ln.get("text") or ""):
                ln = None  # opens like an earlier line this replay: made again
            elif len((ln.get("text") or "").split()) > room(video_t, end):
                ln, said_as = None, {**said_as, "words": most}  # made for more room: made again
        elif self.calls >= MAX_CALLS:
            return None
        else:
            ln = None
            if reply:
                picked = ("reply", heard)
            elif n == 0 and ball:  # a football stretch opens on who has the ball (#205)
                from data.matches import orientation

                picked = ("orientation", orientation(self.header(), past, ball))
            else:  # after the ball, the analyst's next line is the stretch's first stat
                first = n == 0 or (n == 2 and bool(ball))
                picked = self.next_stat(past, first, prefer=self.asked if n else None)
            if not picked:
                return None
            said_as = {
                "kind": picked[0],
                "detail": picked[1],
                "heard": heard,
                # who said it: always the other voice, the lead's call before the first line
                "by": "analyst" if reply else "lead",
                "named": named(self.match_id, m["idx"], n),
                "words": most,
                "v": VERSION,
            }
            if picked[0] == "orientation":  # said at the ball's time, the latest it reads (A-1.4)
                said_as["clock"] = ball["clock"]
            # the comeback is told what the analyst says next, when that line still fits before
            # the next moment, so a question from the lead gets its answer
            answer_at = video_t + most / WORDS_PER_S + TURN_S
            if (
                reply
                and room(answer_at, end) >= MIN_WORDS
                and (topic := self.peek(past, first=bool(ball)))
            ):
                said_as["next"] = topic[0]
        if ln is None:
            failed = False  # a try had a wrong number or a used opener
            for retry in (False, True):
                if self.calls >= MAX_CALLS:
                    return None
                self.calls += 1
                # the same seam as every line: only moments up to the one followed reach the model
                try:
                    said = commentate(stat_moment(m, said_as, reply), list(past))
                except Exception as exc:  # a model outage ends this line, not the moment (#378)
                    log.warning(
                        "stat line after %s failed: %s: %s", m["idx"], type(exc).__name__, exc
                    )
                    said = None
                if said and said.get("text"):  # the checks below see what is said
                    said = {
                        **said,
                        "text": cut(said["text"], int(min(CUT_WORDS, room(video_t, end)))),
                    }
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
                    # nor does either voice say a recent line's phrase: asked once more, told it
                    echo = None if fresh else echoes(said["text"], list(recent))
                    # and it ends before the next moment: a longer one is asked once more (#297)
                    fits = len(said["text"].split()) <= room(video_t, end)
                    if right and not echo and fits and (not stale or retry and fresh):
                        said = {**said, "checked": True, **({"retried": True} if failed else {})}
                        break  # a ball line falls back below
                    if retry:
                        self.overran = not fits
                        log.warning(
                            "stat line after %s dropped: wrong=%s echo=%s fits=%s stale=%s",
                            m["idx"], not right, bool(echo), fits, stale,
                        )  # fmt: skip
                        return None
                    if stale:
                        said_as = {**said_as, "never open with": " ".join(opener(said["text"]))}
                    if echo:
                        said_as = {**said_as, "never say": echo}
                    failed = True
                    continue
                if reply or retry or self.calls >= MAX_CALLS:
                    log.warning("stat line after %s: the model gave no line", m["idx"])
                    # the analyst's turn is the fact itself, so an outage leaves the booth talking;
                    # its numbers are the data's, so it passes the number check by construction
                    text = None if reply else cut(said_as["detail"], int(room(video_t, end)))
                    if not text or self.wrong(text, stat_moment(m, said_as, reply), past):
                        return None
                    said = {
                        "line_id": uuid.uuid4().hex,
                        "sport": m.get("sport"),
                        "match_id": self.match_id,
                        "moment_idx": m["idx"],
                        "text": text,
                        "model": None,
                        "served_by": None,
                        "fallback": True,
                        "checked": True,
                    }
                    break
                self.used.add(said_as["detail"])  # dropped: the next kind gets this slot, once
                self.skip = said_as["kind"]
                try:
                    picked = self.next_stat(past)
                finally:
                    self.skip = None
                if not picked:
                    return None
                said_as = {**said_as, "kind": picked[0], "detail": picked[1]}
                said_as.pop("clock", None)  # a stat is said at its moment's time
            if said_as["kind"] == "orientation" and (
                wrong_orientation(said["text"], m, said_as, self.header(), past)
                or self.stale(said["text"])
            ):
                # built from the data: the model that was rejected didn't serve it (#250)
                said = {**said, "text": said_as["detail"], "fallback": True, "served_by": None}
            key = {"match_id": self.match_id, "after_idx": m["idx"], "n": n}
            ln = self.store.append(
                "lines",
                {
                    **said,
                    "video_t": video_t,
                    "speaker": speaker,
                    "replay_id": self.replay_id,
                    role: {**key, **said_as},
                    # the page's next moment cuts it and drops it if held: never late (#297)
                    "fill": True,
                },
            )
        if reply:
            self.asked = said_as.get("next")  # the analyst answers it next
        else:
            self.used.add(said_as["detail"])
            if not ln.get("fallback"):  # the data's ball line is not the analyst's opener
                self.openers.add(opener(ln["text"]))
        return stat_moment(m, said_as, reply), ln

    def cold_open(
        self, before: list[dict], first: dict, t: float, first_t: float, commentate
    ) -> list[tuple[dict, dict]]:
        """The lines said from video time `t` before the first mapped moment (`first`, at
        `first_t`): the lead welcomes the listener and sets the scene (#221); with no moments
        `before` it, the analyst adds one light line, else the replay goes on into a stretch over
        the last of them, so the analyst's reply is a fact (#297). Said over the last moment
        `before` it, else over `first` with no score yet, so its play never reaches the request.
        Each new line is asked to fit what is left before the first call; a line, cached or new,
        is said only if it ends a turn before it, else the open ends there.
        [(Stat moment, stored Line)] in order."""
        m, history, kickoff = (before[-1], before, False) if before else (first, [], True)
        out, heard = [], ""
        for n, (speaker, ask) in enumerate(OPENING[:1] if before else OPENING):
            lead = speaker == "lead"
            words = int(min(OPEN_WORDS, room(t, first_t)))
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
                    "words": words,
                    "v": VERSION,
                }
            )
            stat = stat_moment(m, said_as, lead)
            # the moment lines' number check on every open line, cached ones too (#224's for the
            # stretches): a number the match doesn't give is never said; nor a stored answer to a
            # welcome since made again; nor one too long for the room, which is made again to fit
            if ln is not None and (
                said_as["heard"] != heard
                or self.wrong(ln.get("text") or "", stat, history)
                or due_after(t, ln.get("text"), 0) > first_t - TURN_S
            ):
                ln, said_as = None, {**said_as, "heard": heard, "words": words}
                stat = stat_moment(m, said_as, lead)
            if ln is None:
                if words < MIN_WORDS:
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
            done = due_after(t, ln.get("text"), 0)  # when it has been said: a turn is no speech
            if done > first_t - TURN_S:
                break
            if not lead:
                self.openers.add(opener(ln["text"]))
            out.append((stat, {**ln, "video_t": t}))
            heard, t = ln["text"], done + TURN_S
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


# a run of this many words two lines share is the same phrase; 4 caught "chelsea have a lot" (#288)
ECHO_WORDS = 5


def named(match_id: str, after_idx: int, n: int) -> bool:
    """Whether the n-th stretch line may use the partner's name: seeded by its place, so a replay
    asks the same; the note reaches only the user message, never the prompt (#297)."""
    rate = NAMED["lead" if n % 2 else "analyst"]
    return random.Random(f"{match_id}:{after_idx}:{n}").random() < rate


ABBREVIATIONS = {
    "st",
    "mr",
    "dr",
    "jr",
    "vs",
    "v",
    "no",
}  # a full stop after these ends no sentence


def cut(text: str, most: int = CUT_WORDS) -> str:
    """The line, or when it runs over `most` words its full sentences that fit; never cut
    mid-sentence, so a first sentence over `most` keeps the whole line."""
    if len(text.split()) <= most:
        return text
    sentences: list[str] = []
    for piece in re.split(r"(?<=[.!?])\s+", text.strip()):
        last = sentences[-1].split()[-1].rstrip(".") if sentences else ""
        if last.lower() in ABBREVIATIONS or (len(last) == 1 and last.isupper()):
            sentences[-1] += " " + piece  # "St. James Park" is one sentence
        else:
            sentences.append(piece)
    kept: list[str] = []
    for sentence in sentences:
        if len(" ".join([*kept, sentence]).split()) > most:
            break
        kept.append(sentence)
    return " ".join(kept) or text


def echoes(text: str, recent: list[str]) -> str | None:
    """The first run of ECHO_WORDS words the line shares with one of the recent lines, else None:
    the two voices never say the same phrase ("Chelsea have a lot to find" from both)."""
    words = re.findall(r"[\w'’]+", text.lower())
    runs = {tuple(words[i : i + ECHO_WORDS]) for i in range(len(words) - ECHO_WORDS + 1)}
    for prev in recent[-RECENT_LINES:]:
        p = re.findall(r"[\w'’]+", prev.lower())
        for i in range(len(p) - ECHO_WORDS + 1):
            if tuple(p[i : i + ECHO_WORDS]) in runs:
                return " ".join(p[i : i + ECHO_WORDS])
    return None


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


def _wrong_clock(words: list, m: dict) -> list[str]:
    """A basketball clock said to the second is held to the second: "ninety seconds to play" at
    1:45 is wrong. "Under thirty seconds" needs the clock under it, "about ninety" may round."""
    if m.get("sport") != "basketball" or not (c := re.match(r"(\d+):(\d+)", str(m.get("clock")))):
        return []
    left, wrong = int(c[1]) * 60 + int(c[2]), []
    for i, n in enumerate(words):
        if not isinstance(n, float) or words[i + 1 : i + 2] not in (["seconds"], ["second"]):
            continue
        if (
            words[i + 2 : i + 3] not in (["to"], ["left"], ["remaining"])
            or "shot" in words[i : i + 7]
        ):
            continue  # "eight seconds on the shot clock" is another clock
        j = i - 1 - (words[i - 1 : i] == ["and"])
        if i and words[j : j + 1] in (["minute"], ["minutes"]) and j:
            mins = words[j - 1]
            mins = mins if isinstance(mins, float) else {"a": 1, "one": 1}.get(mins)
            n += 60 * mins if mins else 0  # "one minute forty-five seconds" is 105
        before = set(words[max(0, i - 2) : i])
        if before & {"under", "inside", "less", "fewer", "within"}:
            ok = left <= n
        elif before & {"over", "more"}:
            ok = left >= n
        elif before & {"about", "around", "roughly", "nearly", "almost", "some", "close"}:
            ok = abs(n - left) <= 15
        else:
            ok = abs(n - left) <= 1
        if not ok:
            wrong.append(f"{n:g} seconds is not the clock, {m['clock']}")
    return wrong


# a claim that is negated, wished for or in the past is no claim about the play now
NOT_NOW = re.compile(
    r"\b(?:no|not|never|without|need|needs|needed|will|would|could|can|might|must|chasing"
    r"|hope|hoping|want|wants|were|was|been|earlier)\b|n't\b"
    r"|\bat (?:kick-off|kickoff|half-time|halftime|the break)\b",
    re.I,
)


def _clause_before(sentence: str, at: int) -> str:
    return re.split(r"[,;:—–]", sentence[:at])[-1]


STREAK = re.compile(
    r"\bback[- ]to[- ]back\b|\bin a row\b|\bon the bounce\b"
    r"|\b(?:straight|consecutive|successive)\b",
    re.I,
)
STREAK_KIND = {  # what a basketball streak is of, and the fewest points each one is worth
    "buckets": 2,
    "baskets": 2,
    "shots": 2,
    "threes": 3,
    "throws": 1,
    "points": 1,
}
NOT_PLAY = {"championships", "titles", "wins", "games", "matches", "seasons", "moments", "finals"}


def _streak_claims(text: str) -> list[tuple[int, str | None]]:
    """Each streak a line claims, as (how many, of what): "back-to-back buckets" (2, "buckets"),
    "three in a row" (3, None), "his third straight bucket" (3, "buckets")."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for hit in STREAK.finditer(sentence):
            if NOT_NOW.search(_clause_before(sentence, hit.start())):
                continue  # "no back-to-back buckets", "Utah need back-to-back buckets"
            words = said(sentence[max(0, hit.start() - 30) : hit.start()])
            after = said(sentence[hit.end() : hit.end() + 30])
            kind = next(
                (w for w in [*words[-2:], *after[:2]] if w in STREAK_KIND or w in NOT_PLAY), None
            )
            n = 2 if re.match(r"back|consecutive|successive", hit[0], re.I) else None
            # the count right before it: "three in a row", "three sixes in a row", "third straight"
            for w in words[-1:] if words[-1:] != [kind] else words[-2:-1]:
                n = int(w) if isinstance(w, float) and w > 1 else ORDINALS.get(w, n)
            if n and kind not in NOT_PLAY:
                out.append((n, kind))
    return out


def _wrong_streak(text: str, m: dict, past: list[dict], header: dict | None) -> list[str]:
    """A basketball streak claim tested against the score sequence: "three straight buckets" needs
    the points to have come with the other side's score standing still. A cricket streak is not
    tested: the moments are not known to hold every ball that could break one (#293)."""
    claims = _streak_claims(text)
    if not claims or m.get("type") == "Stat":
        return []
    wrong = []
    if (
        m.get("sport") == "basketball"
        and header
        and m.get("team") in (header["home"], header["away"])
    ):
        side = "home" if m["team"] == header["home"] else "away"
        other = "away" if side == "home" else "home"
        s = m.get("score") or {}
        # the latest moment the other side's score was lower: they scored after it
        since = next(
            (
                p
                for p in reversed(past)
                if (p.get("score") or {}).get(other, s.get(other)) < s.get(other, 0)
            ),
            None,
        )
        for n, kind in claims:
            each = STREAK_KIND[kind] if kind else 1
            if since and s[side] - since["score"][side] < n * each:
                wrong.append(f"no {n} in a row: {header[other]} scored in between")
    return wrong


def _wrong_span(words: list, m: dict, past: list[dict]) -> list[str]:
    """A cricket batter's runs over a span of balls, "18 off six balls", held to the boundaries
    that batter hit in the last six balls, or to a run of boundaries that spans exactly six balls
    ("three sixes in four balls" is 18 off four). "Need 22 from 7 balls" is the chase."""
    if (
        m.get("sport") != "cricket"
        or m.get("type") not in ("Six", "Four")
        or "batter" not in m.get("players", {})
    ):
        return []
    who, now = m["players"]["batter"], _ball(m)
    mine = [
        p
        for p in [*past, m]
        if p.get("players", {}).get("batter") == who and p["type"] in ("Six", "Four")
    ]
    s, d = m.get("score") or {}, m.get("detail") or {}
    wrong = []
    for i, (r, prep, b) in enumerate(zip(words, words[1:], words[2:], strict=False)):
        if not (isinstance(r, float) and prep in ("off", "from", "in") and isinstance(b, float)):
            continue
        unit, prev = words[i + 3 : i + 4], words[i - 1 : i]
        if prev and (prev[0] in ORDINALS or prev[0] in ("a", "another", "his", "the")):
            continue  # "his third six in four balls" is a six, not 6 runs
        if unit not in (["balls"], ["deliveries"]) or b < 2:
            continue
        if "target" in s and (r, b) == (s["target"] - s["runs"], d.get("balls_left")):
            continue  # the chase
        window = sum(
            (p.get("detail") or {}).get("runs_batter") or 0 for p in mine if now - _ball(p) < b
        )
        runs = {
            sum((p.get("detail") or {}).get("runs_batter") or 0 for p in mine[-k:])
            for k in range(1, len(mine) + 1)
            if now - _ball(mine[-k]) + 1 == b
        }
        if r != window and r not in runs:
            wrong.append(f"{r:g} off {b:g} balls is not {who}'s, {window:g} off the last {b:g}")
    return wrong


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
    r"(?:(?:take|takes|retake|retakes|regain|regains|reclaim|reclaims|have|has|hold|holds)"
    r"\s+(?:the|a)\s+lead"
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


def _wrong_score(text: str, m: dict) -> list[str]:
    """Each football score a line states now that is neither the score nor the shootout's:
    "Tottenham still lead one-nil" at 1-2 (#297's judges). A score in the past or negated ("it
    was one-nil at the break"), or another game's ("a 2-1 win"), is no claim about now."""
    s, so = m["score"], (m.get("detail") or {}).get("shootout")
    scores = [sorted((x["home"], x["away"])) for x in (s, so) if x]
    wrong = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if sentence.rstrip().endswith("?"):
            continue
        for start, end, pair in _said_scores(sentence, m):
            before = _clause_before(sentence, start)
            if (
                NOT_NOW.search(before)
                # "a one-two", "the 2-1", a tally "by five to one", a change "from 1-0"
                or re.search(r"\b(?:a|an|the|by|from)\s*$", before, re.I)
                or sorted(pair) in scores
            ):
                continue
            wrong.append(f"{sentence[start:end]} is not the score ({s['home']}-{s['away']})")
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
    wrong += (
        _wrong_clock(words, m) + _wrong_streak(text, m, past, header) + _wrong_span(words, m, past)
    )
    if "home" in s and header:
        wrong += _false_lead(text, m, header) + _wrong_margin(text, m, header)
        if m.get("sport") == "football":
            wrong += _wrong_score(text, m)
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
    r"(?:\b(?:needs?|needed|needing|look(?:ing)? for) (?:a|another) six\b"
    r"|\b(?:unless|if|can|could|(?:needs?|has|have|had|try|trying) to)\b[^.!?]*?"
    r"\bfind(?:s|ing)? (?:a|another) six\b)"
    r"(?!,? and (?:\w+ )?(?:got|gets|found|finds) (?:one|it))"  # "needed a six, and got one"
    r"|\bfind(?:s|ing)? (?:a|another) six\b[^.!?,;]*\?",
    re.I,
)
# an earlier six recalled: "a dot ball after the six", "found a six last over"
PAST_SIX = re.compile(r"\bafter (?:the|that|his) six\b|\bsix (?:earlier|last over)\b", re.I)
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
    # a wicket line may recall the bowler's earlier moments: "has a six and a last-ball two"
    if (
        kind != "Wicket"
        and m.get("outcome") != "6 runs"
        and SIX.search(PAST_SIX.sub("", WANTED_SIX.sub("", text)))
    ):
        wrong.append(f"a six is called, but the ball was {m.get('outcome')}")
    if won := re.match(r"(.+?) win\b", d.get("chase", "")):
        wrong += _wrong_winner(text, m, won[1])
    if kind == "Wicket":
        out = m.get("outcome")
        wrong += [
            f"{how} is called, but the wicket was {out}"
            for how, said in HOW_OUT.items()
            if how != out and said.search(text)
        ]
    return wrong


def _wrong_winner(text: str, m: dict, winner: str) -> list[str]:
    """ "Nepal win it!" on the ball Netherlands won on; "Nepal need a six" names no winner."""
    from data.matches import match_header

    try:
        side, names = _sides(match_header(m["match_id"]))
    except KeyError:  # not a bundled match: no team names to look for
        return []
    if (won := side.get(winner.lower())) is None:
        return []
    said = rf"\b({names})\s+(?:(?:have|has)\s+)?(?:wins?|won)\b(?! the toss)"
    called = re.finditer(said, text, re.I)
    if any(side.get(c[1].lower()) != won for c in called):
        return [f"the wrong side is called the winner: {winner} win"]
    return []


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
    if m.get("type") == "Shot":
        ended = SHOT_ENDED.get(m.get("outcome"))
        wrong += [
            f"{'a save' if call == 'saved' else call} is called, but the shot was {ended}"
            for call, said_it in (
                ("saved", SAVED),
                ("blocked", BLOCKED),
                ("off target", OFF_TARGET),
            )
            if ended and call not in CAN_CALL[ended] and _says(said_it, text)
        ]
    if m.get("type") == "Shot" and not goal and not ENDED.search(text):
        wrong.append(f"the line never says how the shot ended: {m.get('outcome')}")
    return wrong + _wrong_level(text, m) + _wrong_shootout(text, m)


def _says(rx: re.Pattern, text: str) -> bool:
    """Whether the line says it, not "not wide" or "wasn't saved"."""
    return any(
        not re.search(r"(?:\b(?:not|never|no)|n't)\s+(?:\w+\s+)?$", text[: hit.start()], re.I)
        for hit in rx.finditer(text)
    )


# how a shot that is no goal ended, and what a line may call it: a keeper's block is a save
SHOT_ENDED = {
    "Blocked": "blocked",
    "Saved": "saved",
    "Off T": "off target",
    "Wayward": "off target",
}
# how a line may call each ending: a keeper's save can be a block, a blocked shot can deflect wide
CAN_CALL = {
    "blocked": {"blocked", "off target"},
    "saved": {"saved", "blocked"},
    "off target": {"off target"},
}
BLOCKED = re.compile(r"\bblock(?:s|ed|ing)?\b", re.I)
OFF_TARGET = re.compile(r"\b(?:wide|off target|over the bar|skie[sd]|sails? over)\b", re.I)
# "still level", "all square", "the scores are level": a claim about now, on any football moment;
# never "were level", "to level it" or a question
LEVEL_NOW = re.compile(
    r"(?:\b(?:still|now|back|remains?|stays?|are|is|it's|we're)\s+(?:all\s+)?level\b"
    r"|\blevel (?:at|on|pegging)\b|\ball square\b|\bscores? (?:are |is )?level\b)"
    r"(?!\s+with\b)",  # "level with the last defender" is a place on the pitch
    re.I,
)


def _wrong_level(text: str, m: dict) -> list[str]:
    """ "Still level" at 3-2, on a card, a sub or a save as much as on a goal."""
    s = m.get("score") or {}
    if "home" not in s or s["home"] == s["away"] or m.get("type") == "Full time":
        return []  # a shootout's match is level: "still level at three" is the match
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if sentence.rstrip().endswith("?"):
            continue
        for hit in LEVEL_NOW.finditer(sentence):
            if not NOT_NOW.search(_clause_before(sentence, hit.start()) + hit[0]):
                return [f"the scores are not level: {s['home']}-{s['away']}"]
    return []


SCORE_WORD = r"\d+|nil|zero|one|two|three|four|five|six|seven|eight|nine|ten"
SCORE_AT = {**{w: i for i, w in enumerate(UNITS[:11])}, "nil": 0}
# a score said as such: "four-two", "two to one", "two one", "three all", "one apiece"
SAID_SCORE = re.compile(
    rf"\b({SCORE_WORD})(?:\s*[-–]\s*|\s+to\s+|\s+)({SCORE_WORD})\b"
    rf"|\b({SCORE_WORD})[- ](?:all|apiece|each)\b",
    re.I,
)
# where a score is said to be the shootout's: right before "in the shootout", or right after
# "lead the shootout"
IN_SHOOTOUT = re.compile(
    r"^[,\s]*(?:\w+\s+){0,2}?(?:in|on) (?:the |this )?(?:penalty )?shoot-?out\b"
    r"|^[,\s]*(?:\w+\s+){0,2}?on (?:penalties|pens|spot[- ]kicks)\b",
    re.I,
)


def _said_scores(sentence: str, m: dict) -> list[tuple[int, int, tuple[int, int]]]:
    """Each score a sentence says, with where it ends and where it starts, either way round:
    "Argentina three, France three", "four-two", "three all"."""
    from data.matches import match_header

    def n(w: str) -> int:
        return int(w) if w.isdigit() else SCORE_AT[w.lower()]

    out = [
        (hit.start(), hit.end(), (n(hit[1]), n(hit[2])) if hit[1] else (n(hit[3]), n(hit[3])))
        for hit in SAID_SCORE.finditer(sentence)
    ]
    try:
        side, names = _sides(match_header(m["match_id"]))
    except KeyError:  # not a bundled match: no team names to look for
        return out
    team = rf"\b({names})\s+({SCORE_WORD})\b"
    for hit in re.finditer(rf"{team},?\s+(?:and\s+)?{team}", sentence, re.I):
        if side[hit[1].lower()] != side[hit[3].lower()]:  # "Argentina three, France three"
            out.append((hit.start(), hit.end(), (n(hit[2]), n(hit[4]))))
    return out


def _wrong_shootout(text: str, m: dict) -> list[str]:
    """A score said to be the shootout's is the shootout's: "Argentina three, France three in the
    shootout" at 1-1 on kicks is the match score. A sentence that also gives the kicks ("three
    all, but it's three to one in the shootout") says both."""
    so = (m.get("detail") or {}).get("shootout")
    if not so:
        return []
    kicks = sorted((so["home"], so["away"]))
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        scores = _said_scores(sentence, m)
        claimed = [
            pair
            for start, end, pair in scores
            if IN_SHOOTOUT.match(sentence[end:])
            or re.search(r"\bthe shoot-?out\s*(?:is\s+|at\s+)?$", sentence[:start], re.I)
        ]
        if claimed and all(sorted(pair) != kicks for _, _, pair in scores):
            a, b = claimed[0]
            return [f"{a}-{b} is not the shootout, {so['home']}-{so['away']}"]
    return []


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
    if not (first := wrong_numbers(line["text"], moment, header, history)):
        return {**line, "checked": True}
    again = commentate(moment, history)
    if again and again.get("text"):
        if not (wrong := wrong_numbers(again["text"], moment, header, history)):
            # the replay corrects the recorded first try with it
            rejected = {**line, "wrong": first}  # the auto-fix tells the model why (#245)
            return {**again, "rejected": rejected, "retried": True, "checked": True}
    else:  # nothing usable the second time: the first try is the one the producer fixes
        again, wrong = line, wrong_numbers(line["text"], moment, header, history)
    tried = {"tried": again["text"], "wrong": wrong, "checked": True}
    # built from the data: the model that was rejected didn't serve it (#250)
    return {
        **again,
        "text": fallback_text(header, moment),
        "fallback": True,
        "served_by": None,
        **tried,
    }


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
    r"(?!\s+(?:again|from open play|(?:yet\s+)?(?:for\s+\w+(?:\s+\w+){0,2}\s+)?(?:yet\s+)?(?:since"
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
# a goal said to have happened, the named player's own: "with Merritt Mathias finding the net" on
# her shot off target (#352). Never a wish ("looking to score", "could find the net"), the noun
# ("the scores are level"), a denial (NOT_SCORED) or an own goal, whose scorer has no shot goal
SCORED = re.compile(
    r"\b(?:scored|scores|nets|netted|(?:find|finds|finding|found) the (?:back of the )?net"
    r"|on the score ?sheet)\b",
    re.I,
)
NOT_YET = re.compile(r"\b(?:to|could|would|can|will|might|may|should|if|the)\s+(?:\w+\s+)?$", re.I)
NTH_GOAL = {"first": 1, "second": 2, "third": 3, "fourth": 4, "brace": 2}
HALVES_SAID = {"second half": 2, "first half of extra time": 3, "second half of extra time": 4}
# a lead said to move ("extend their lead to eighteen", "cutting the gap"): wrong at a moment
# that scored nothing
LEAD_MOVED = re.compile(
    r"\b(?:extend|stretch|widen|increas|grow|grew|cut|trim|narrow|reduc|clos)\w{0,4}\b"
    r"(?:\s+\w+){0,2}\s+(?:lead|gap|deficit|advantage|margin)\b",
    re.I,
)
MAY_MOVE = re.compile(r"\b(?:to|could|would|can|will|might|may|should|if)\s+(?:\w+\s+)?$", re.I)
NOW_IN = r"\b(?:we're|we are|it's|it is|deep|now|already)\s+(?:\w+\s+)?(?:in|into)\s+the\s+"


def _named_before(named: list[tuple[int, str]], at: int) -> str | None:
    """The player named last before `at`, whose claim it is: "Messi scored, but Di María hasn't"."""
    return next((name for start, name in reversed(named) if start < at), None)


def wrong_claims(text: str, past: list[dict], question: str = "") -> list[str]:
    """What a football answer says that the numbers check can't see: a player's goals so far, each
    claim tied to the player named last before it ("he" to the last named in the answer, else in
    the question), and that the match is now in a half it hasn't reached ("we're deep in the
    second half of extra time" at 105:41; never "in the second half they need to come out
    stronger")."""
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
    # a claimed goal (SCORED) may be a shootout kick: "Argentina lead after Paulo Dybala scores"
    netted = {p["players"].get("shooter") for p in past if p.get("outcome") == "Goal"}
    names = {n for p in past for n in (p.get("players") or {}).values() if isinstance(n, str)}
    surnames = Counter(n.split()[-1] for n in names)
    said = {n: n if surnames[n.split()[-1]] > 1 else n.split()[-1] for n in names}  # two Martínez

    def named_in(words: str, any_case: bool = False) -> list[tuple[int, str]]:
        """Full names in any case; in answer prose a surname only as the data spells it, so "his
        shot rose" is never Danny Rose. A question ("how did messi score?") matches any case."""
        return sorted(
            (hit.start(), name)
            for name in names
            for hit in re.finditer(
                rf"\b(?:(?i:{re.escape(name)})|{re.escape(said[name])})\b",
                words,
                re.I if any_case else 0,
            )
        )

    everyone, asked, offset = named_in(text), named_in(question, any_case=True), 0
    for clause in re.split(r"(?<=[.!?;])\s+", text):  # a clause each: "Messi; Mbappé's brace"
        offset = text.index(clause, offset)
        named = named_in(clause)

        for hit in NOT_SCORED.finditer(clause):
            # "no goal (yet) for Lionel Messi" is Messi's, even after "Lautaro is searching, but";
            # "no goal for France (while Messi...)" is nobody's
            after = re.match(r"\s+(?:yet\s+)?for\s+", clause[hit.end() :])
            rest = clause[hit.end() + after.end() :] if after else ""
            for_whom = next(
                (
                    n
                    for n in names
                    if re.match(rf"(?:{re.escape(n)}|{re.escape(said[n])})\b", rest, re.I)
                ),
                None,
            )
            # "He hasn't scored": the player named last in the answer, else in the question
            he = re.search(
                r"\b(?:he|she)(?:['’]s)?(?:\s+\w+){0,2}\s*$", clause[: hit.start()], re.I
            )
            him = he and (
                _named_before(everyone, offset + hit.start())
                or _named_before(asked, len(question) + 1)
            )
            name = for_whom if after else _named_before(named, hit.start()) or him
            if name and goals[name]:
                wrong.append(f"{name} has scored {goals[name]} so far")
        for hit in NTH.finditer(clause):
            n = NTH_GOAL.get(next(g for g in hit.groups() if g).lower(), 3)
            if (name := _named_before(named, hit.start())) and n > goals[name]:
                wrong.append(f"{name} has scored {goals[name]} so far, not {n}")
        denied = [hit.span() for hit in NOT_SCORED.finditer(clause)]
        for hit in SCORED.finditer(clause):
            if (
                re.search(r"\bown goal\b", clause, re.I)
                or NOT_YET.search(clause[: hit.start()])
                or any(a <= hit.start() < b for a, b in denied)
            ):
                continue
            if (name := _named_before(named, hit.start())) and name not in netted:
                wrong.append(f"{name} has not scored so far")
    return wrong


def wrong_lead_move(text: str, past: list[dict]) -> list[str]:
    """A lead said to grow or shrink at a moment whose score is the one before it: "What just
    happened?" on Vujacic's steal at 120-102 was answered "Lakers extend their lead to eighteen"
    (#389), the free throws before it, not the steal. "Could extend their lead" is fine."""
    if len(past) < 2 or past[-1].get("score") is None or past[-1]["score"] != past[-2].get("score"):
        return []
    if not any(not MAY_MOVE.search(text[: hit.start()]) for hit in LEAD_MOVED.finditer(text)):
        return []
    m = past[-1]
    lead = (m.get("detail") or {}).get("lead")
    return [
        f"the score did not change at this moment ({m.get('type')}){f'; {lead}' if lead else ''}"
    ]


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
        wrong = (
            wrong_answer(answer, question, past, lines)
            + wrong_claims(answer["text"], past, question)
            + wrong_lead_move(answer["text"], past)
        )
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
        # reminders in the user message: the analyst's prompt is the task's fingerprint (#297)
        **({"length": f"at most {words} words"} if (words := said_as.get("words")) else {}),
        **(
            {"angle": ANGLES[kind]} if not reply and (kind := said_as.get("kind")) in ANGLES else {}
        ),
        # the comeback may ask about what the analyst says next, so the next line answers it
        **(
            {f"{NAMES['analyst']}'s next point is about": said_as["next"]}
            if "next" in said_as
            else {}
        ),
        # how big the moment is: the pair matches its delivery to it (#378); the voice reads it too
        "intensity": "calm" if said_as.get("kind") == OPEN else intensity(m),
        f"{NAMES[by]} just said": said_as["heard"],
        **({"never open with": said_as["never open with"]} if "never open with" in said_as else {}),
        **({"never say": said_as["never say"]} if "never say" in said_as else {}),
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
