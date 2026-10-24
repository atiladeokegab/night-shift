"""Colour commentary between the big moments (#130): stat lines that fill each quiet stretch of a
video-mapped replay. An insight is a synthetic "Stat" moment whose detail is built only from the
moments up to the one it follows and the pre-match pack, and it goes through the same commentate
call as any line, so the Mubit task stays one task. Insight lines are kept in the store and reused
by later replays of the same match."""

from collections import Counter

from core import predict

WORDS_PER_S = 2.7  # a line has likely finished speaking after its words at this rate
PAUSE_S = 2.0  # then this breath before the next insight
CLEAR_S = 6.0  # no insight starts closer than this to the next mapped moment
MAX_CALLS = 160  # new insight calls per replay; cached ones are free
REPLY_EVERY = 4  # every 4th line in a quiet stretch is the lead replying to the analyst
RECENT = 6  # the key moments that count as recent play for momentum


def due_after(t: float, text: str | None) -> float:
    """When the next insight is due after a line said at video time `t`."""
    return t + len(str(text or "").split()) / WORDS_PER_S + PAUSE_S


def _who(m: dict) -> str | None:
    """The moment's main actor: the first role it names (shooter, batter, driver)."""
    return next(iter((m.get("players") or {}).values()), None)


def _profiles(pack, past):
    if not pack:
        return []
    out, zones = [], []
    seen = [n for m in reversed(past) for n in (m.get("players") or {}).values()]
    # then the rest of the roster: a pre-match record is known before the match starts
    rest = sorted(pack["players"], key=lambda n: -pack["players"][n].get("games", 0))
    for name in dict.fromkeys(seen + rest):
        text = predict.profile_text(pack, past, len(past) - 1, name).splitlines()
        if text[0].startswith("No pre-match"):
            continue
        out.append(" ".join(dict.fromkeys([text[0], text[-1]])))  # the record and tonight
        who = text[0].split(" (")[0]
        zones += [f"{who}, {row.lstrip('- ')}" for row in text[1:] if row.startswith("- ")]
    return out + zones  # then each zone (or cricket phase) on its own, for the long stretches


def _odds(pack, past):
    if not pack or pack["sport"] not in predict.SHOTS:
        return []
    rows = predict.odds_text(pack, past, len(past) - 1).splitlines()[1:]
    rows.sort(key=lambda r: not r.startswith(f"{past[-1].get('team')}:"))  # this team first
    return [f"Next to score, pre-match record blended with tonight: {r}" for r in rows if "%" in r]


def _tallies(pack, past):
    out = []
    for key, label in ((_who, "player"), (lambda m: m.get("team"), "team")):
        for name in dict.fromkeys(key(m) for m in reversed(past)):
            if not name:
                continue
            mine = [m for m in past if key(m) == name]
            counts = Counter(
                f"{m['type']} ({m['outcome']})" if m.get("outcome") else m["type"] for m in mine
            )
            said = ", ".join(f"{k} x{v}" for k, v in counts.items())
            # basketball keeps the shooter's running total on each basket
            pts = [(m.get("detail") or {}).get("player_points") for m in mine]
            pts = [p for p in pts if p is not None] if label == "player" else []
            total = f"; {pts[-1]} points in all" if pts else ""
            out.append(f"{name} tonight, in the key moments so far: {said}{total}")
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
        f"P{c['pos']} {c['driver']} {c['gap']}" for c in top if c.get("gap") not in ("", "leader")
    ]
    if gaps:
        out.append(f"Lap {s.get('lap')} of {s.get('laps')}, gaps to the leader: " + ", ".join(gaps))
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
            if (i := ln.get("insight") or ln.get("reply")) and i.get("match_id") == match_id
        }
        self.used: set[str] = set()
        self.turn = 0
        self.calls = 0
        self._pack = None

    def pack(self, m: dict):
        if self._pack is None:
            self._pack = predict.load_pack(m.get("sport", ""), self.match_id) or {}
        return self._pack

    def next_stat(self, past: list[dict]) -> tuple[str, str] | None:
        """The next kind in turn with a detail not said yet in this replay."""
        for i in range(len(KINDS)):
            kind, make = KINDS[(self.turn + i) % len(KINDS)]
            for detail in make(self.pack(past[-1]), past):
                if detail not in self.used:
                    self.turn += i + 1
                    return kind, detail
        return None

    def line(
        self, past: list[dict], n: int, video_t: float, commentate, before: str | None = None
    ) -> tuple[dict, dict] | None:
        """The n-th line in the quiet stretch after past[-1]: the moment it is said over and its
        stored Line, the cached one, else one new commentate call. None ends the stretch. The
        analyst speaks the insights and hears the line before it (`before`); now and then the
        lead replies to the analyst."""
        m = past[-1]
        reply = n % REPLY_EVERY == REPLY_EVERY - 1
        role, speaker = ("reply", "lead") if reply else ("insight", "analyst")
        ln = self.cached.get((m["idx"], n))
        if ln is not None and role in ln:
            said_as = ln[role]
            if not reply and said_as["detail"] in self.used:  # another replay's: never said twice
                return None
        elif self.calls >= MAX_CALLS:
            return None
        else:
            ln = None
            heard = " ".join(str(before or "").split())  # one line: it must not forge a field
            picked = ("reply", heard) if reply else self.next_stat(past)
            if not picked:
                return None
            said_as = {"kind": picked[0], "detail": picked[1], "heard": heard}
        stat = stat_moment(m, said_as, reply)
        if ln is None:
            self.calls += 1
            # the same seam as every line: only moments up to the one followed reach the model
            said = commentate(stat, list(past))
            if not said or not said.get("text"):
                return None
            key = {"match_id": self.match_id, "after_idx": m["idx"], "n": n}
            ln = self.store.append(
                "lines", {**said, "video_t": video_t, "speaker": speaker, role: {**key, **said_as}}
            )
        if not reply:
            self.used.add(said_as["detail"])
        return stat, ln


def stat_moment(m: dict, said_as: dict, reply: bool) -> dict:
    """The synthetic Stat moment an insight or reply is said over: moment m's team, players and
    score, with Details of who speaks, the line it hears and (not for a reply) the stat."""
    # m's own detail stays out (it would be called again); the score line needs these
    keep = {k: v for k, v in (m.get("detail") or {}).items() if k in ("balls_left", "shootout")}
    said_to = {"speaker": "lead" if reply else "analyst", "Partner just said": said_as["heard"]}
    stat = {} if reply else {"stat": said_as["detail"]}
    return {**m, "type": "Stat", "outcome": said_as["kind"], "detail": {**keep, **said_to, **stat}}


def said_over(line: dict, load_moments) -> list[dict] | None:
    """The moments an insight or reply line was said over, its Stat moment last: so a producer's
    fix goes back with that line's own request, not its moment's. None for a moment's line."""
    said_as = line.get("insight") or line.get("reply")
    if not said_as:
        return None
    moments = load_moments(said_as["match_id"])
    i = next(i for i, m in enumerate(moments) if m["idx"] == said_as["after_idx"])
    return [*moments[: i + 1], stat_moment(moments[i], said_as, "reply" in line)]
